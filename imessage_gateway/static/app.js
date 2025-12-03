const chatList = document.getElementById('chat-list');
const chatTitle = document.getElementById('chat-title');
const messagesDiv = document.getElementById('messages');
const sendForm = document.getElementById('send-form');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');

// Settings elements
const settingsBtn = document.getElementById('settings-btn');
const settingsModal = document.getElementById('settings-modal');
const settingsClose = document.getElementById('settings-close');
const settingsSave = document.getElementById('settings-save');
const settingsCancel = document.getElementById('settings-cancel');
const settingPreventSleep = document.getElementById('setting-prevent-sleep');
const settingVimBindings = document.getElementById('setting-vim-bindings');
const settingCustomCss = document.getElementById('setting-custom-css');
const customCssStyle = document.getElementById('custom-css');

let currentChatId = null;
let currentRecipient = null;
let websocket = null;
let lastMessageId = 0;
let allMessages = [];  // Store all messages for current chat
let currentConfig = {}; // Store current configuration

async function loadChats() {
    try {
        const res = await fetch('/chats?limit=100');
        const chats = await res.json();
        renderChats(chats);
    } catch (err) {
        console.error('Failed to load chats:', err);
        chatList.innerHTML = '<div class="empty-state">Failed to load chats</div>';
    }
}

function getChatDisplayName(chat) {
    // For 1:1 chats, prefer identifier (phone/email)
    if (chat.identifier && !chat.identifier.startsWith('chat')) {
        return chat.identifier;
    }

    // For group chats, use display_name if valid, otherwise show participants
    const guidPattern = /^chat\d+$/;
    const hasValidDisplayName = chat.display_name && !guidPattern.test(chat.display_name);
    if (hasValidDisplayName) {
        return chat.display_name;
    }

    // Show participants for group chats
    if (chat.participants && chat.participants.length > 0) {
        // Format as "person1, person2, ..." (truncate last 4 digits of phone for privacy)
        const formatted = chat.participants.map(p => {
            if (p.startsWith('+') && p.length > 4) {
                return '...' + p.slice(-4);
            }
            return p;
        });
        return formatted.join(', ');
    }

    return 'Unknown';
}

function renderChats(chats) {
    if (chats.length === 0) {
        chatList.innerHTML = '<div class="empty-state">No chats found</div>';
        return;
    }
    chatList.innerHTML = chats.map(chat => `
        <div class="chat-item" data-id="${chat.rowid}" data-identifier="${chat.identifier || ''}">
            <div class="chat-name">${getChatDisplayName(chat)}</div>
            <div class="chat-identifier">${chat.identifier || ''}</div>
        </div>
    `).join('');

    chatList.querySelectorAll('.chat-item').forEach(item => {
        item.addEventListener('click', () => selectChat(item));
    });
}

function selectChat(item) {
    chatList.querySelectorAll('.chat-item').forEach(i => i.classList.remove('active'));
    item.classList.add('active');

    currentChatId = parseInt(item.dataset.id, 10);
    currentRecipient = item.dataset.identifier;
    const name = item.querySelector('.chat-name').textContent;
    chatTitle.textContent = name;

    messageInput.disabled = !currentRecipient;
    sendBtn.disabled = !currentRecipient;
    if (!currentRecipient) {
        messageInput.placeholder = 'Cannot send (no recipient identifier)';
    } else {
        messageInput.placeholder = 'Type a message...';
    }

    lastMessageId = 0;
    allMessages = [];
    loadMessages();
    connectWebSocket();
}

async function loadMessages() {
    if (!currentChatId) return;
    try {
        let url = `/messages?chat_id=${currentChatId}&limit=100`;
        const res = await fetch(url);
        const messages = await res.json();
        allMessages = messages;
        renderMessages(allMessages);
        if (messages.length > 0) {
            lastMessageId = Math.max(...messages.map(m => m.rowid));
        }
    } catch (err) {
        console.error('Failed to load messages:', err);
        messagesDiv.innerHTML = '<div class="empty-state">Failed to load messages</div>';
    }
}

// Time gap threshold for showing timestamp separator (in minutes)
const TIMESTAMP_GAP_MINUTES = 60;

function renderMessages(messages) {
    if (messages.length === 0) {
        messagesDiv.innerHTML = '<div class="empty-state">No messages</div>';
        return;
    }
    // Messages come newest first, reverse for display
    const sorted = [...messages].sort((a, b) => a.rowid - b.rowid);

    let html = '';
    let lastTimestamp = null;

    for (const msg of sorted) {
        // Check if we need a timestamp separator
        if (msg.timestamp) {
            const msgTime = new Date(msg.timestamp);
            if (!lastTimestamp || (msgTime - lastTimestamp) > TIMESTAMP_GAP_MINUTES * 60 * 1000) {
                html += `<div class="timestamp-separator">${formatTimeSeparator(msgTime)}</div>`;
            }
            lastTimestamp = msgTime;
        }
        html += messageHtml(msg);
    }

    messagesDiv.innerHTML = html;
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function appendMessages(newMessages) {
    // Add new messages to our collection, avoiding duplicates
    const existingIds = new Set(allMessages.map(m => m.rowid));
    for (const msg of newMessages) {
        if (!existingIds.has(msg.rowid)) {
            allMessages.push(msg);
        }
    }
    // Re-render with all messages sorted
    renderMessages(allMessages);
}

// Tapback emoji mapping
const TAPBACK_EMOJI = {
    love: '❤️',
    like: '👍',
    dislike: '👎',
    laugh: '😂',
    emphasize: '‼️',
    question: '❓'
};

function isImageMimeType(mimeType) {
    if (!mimeType) return false;
    return mimeType.startsWith('image/');
}

function isVideoMimeType(mimeType) {
    if (!mimeType) return false;
    return mimeType.startsWith('video/');
}

function isBrowserPlayableVideo(mimeType) {
    // Browsers generally support mp4/webm, but not quicktime/mov
    if (!mimeType) return false;
    const playable = ['video/mp4', 'video/webm', 'video/ogg'];
    return playable.includes(mimeType.toLowerCase());
}

function renderAttachments(attachments) {
    if (!attachments || attachments.length === 0) return '';

    return attachments.map(att => {
        if (isImageMimeType(att.mime_type)) {
            // For HEIC, browsers may not support it - show anyway, they'll see broken image
            // Could add server-side conversion in future
            return `
                <div class="attachment attachment-image">
                    <a href="${att.url}" target="_blank">
                        <img src="${att.url}" alt="${escapeHtml(att.filename || 'Image')}" loading="lazy">
                    </a>
                </div>
            `;
        } else if (isVideoMimeType(att.mime_type)) {
            if (isBrowserPlayableVideo(att.mime_type)) {
                // Browser can play natively (MP4, WebM, etc.)
                const poster = att.thumbnail_url ? `poster="${att.thumbnail_url}"` : '';
                return `
                    <div class="attachment attachment-video">
                        <video controls preload="metadata" ${poster}>
                            <source src="${att.url}" type="${att.mime_type}">
                            <a href="${att.url}">Download video</a>
                        </video>
                    </div>
                `;
            } else if (att.stream_url) {
                // MOV/QuickTime with ffmpeg transcoding available
                const poster = att.thumbnail_url ? `poster="${att.thumbnail_url}"` : '';
                return `
                    <div class="attachment attachment-video">
                        <video controls preload="none" ${poster}>
                            <source src="${att.stream_url}" type="video/mp4">
                            <a href="${att.url}">Download video</a>
                        </video>
                    </div>
                `;
            } else {
                // No ffmpeg - show as downloadable video file with thumbnail if available
                const sizeKb = Math.round(att.total_bytes / 1024);
                const sizeStr = sizeKb > 1024 ? `${(sizeKb / 1024).toFixed(1)} MB` : `${sizeKb} KB`;
                if (att.thumbnail_url) {
                    return `
                        <div class="attachment attachment-video-download">
                            <a href="${att.url}" download="${escapeHtml(att.filename || 'video')}">
                                <img src="${att.thumbnail_url}" alt="Video thumbnail" class="video-thumbnail">
                                <div class="video-overlay">
                                    <span class="download-icon">⬇️</span>
                                    <span class="file-size">${sizeStr}</span>
                                </div>
                            </a>
                        </div>
                    `;
                }
                return `
                    <div class="attachment attachment-file attachment-video-file">
                        <a href="${att.url}" download="${escapeHtml(att.filename || 'video')}">
                            <span class="file-icon">🎬</span>
                            <span class="file-name">${escapeHtml(att.filename || 'Video')}</span>
                            <span class="file-size">${sizeStr}</span>
                        </a>
                    </div>
                `;
            }
        } else {
            // Generic file attachment
            const sizeKb = Math.round(att.total_bytes / 1024);
            const sizeStr = sizeKb > 1024 ? `${(sizeKb / 1024).toFixed(1)} MB` : `${sizeKb} KB`;
            return `
                <div class="attachment attachment-file">
                    <a href="${att.url}" download="${escapeHtml(att.filename || 'file')}">
                        <span class="file-icon">📎</span>
                        <span class="file-name">${escapeHtml(att.filename || 'Attachment')}</span>
                        <span class="file-size">${sizeStr}</span>
                    </a>
                </div>
            `;
        }
    }).join('');
}

function messageHtml(msg) {
    const cls = msg.is_from_me ? 'from-me' : 'from-them';

    // Handle tapback reactions - render as small inline reaction
    if (msg.tapback_type) {
        const emoji = TAPBACK_EMOJI[msg.tapback_type] || msg.tapback_type;
        return `
            <div class="message tapback ${cls}">
                <span class="tapback-emoji">${emoji}</span>
            </div>
        `;
    }

    const text = msg.text || '';
    const attachmentsHtml = renderAttachments(msg.attachments);

    // If we only have attachments and no text, don't show empty text bubble
    if (!text && attachmentsHtml) {
        return `
            <div class="message ${cls}">
                ${attachmentsHtml}
            </div>
        `;
    }

    return `
        <div class="message ${cls}">
            ${text ? `<div class="text">${escapeHtml(text)}</div>` : ''}
            ${attachmentsHtml}
        </div>
    `;
}

function formatTimeSeparator(date) {
    const now = new Date();
    const isToday = date.toDateString() === now.toDateString();
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    const isYesterday = date.toDateString() === yesterday.toDateString();

    if (isToday) {
        return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    } else if (isYesterday) {
        return 'Yesterday ' + date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    } else {
        return date.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' +
               date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function connectWebSocket() {
    // Close existing connection if any
    if (websocket) {
        websocket.close();
        websocket = null;
    }

    if (!currentChatId) return;

    // Build WebSocket URL
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws?chat_id=${currentChatId}`;

    websocket = new WebSocket(wsUrl);

    websocket.onopen = () => {
        console.log('WebSocket connected');
        // Tell server to start from our current position
        if (lastMessageId > 0) {
            websocket.send(JSON.stringify({
                type: 'set_after_rowid',
                rowid: lastMessageId
            }));
        }
    };

    websocket.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.type === 'messages' && data.data.length > 0) {
            appendMessages(data.data);
            lastMessageId = data.last_rowid;
        }
        // Ignore ping messages
    };

    websocket.onclose = () => {
        console.log('WebSocket closed, reconnecting in 3s...');
        setTimeout(() => {
            if (currentChatId) {
                connectWebSocket();
            }
        }, 3000);
    };

    websocket.onerror = (err) => {
        console.error('WebSocket error:', err);
    };
}

sendForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = messageInput.value.trim();
    if (!text || !currentRecipient) return;

    sendBtn.disabled = true;
    messageInput.disabled = true;

    try {
        const res = await fetch('/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ recipient: currentRecipient, message: text })
        });
        if (!res.ok) {
            const err = await res.json();
            alert('Failed to send: ' + (err.detail || 'Unknown error'));
        } else {
            messageInput.value = '';
            // WebSocket will receive the new message automatically
        }
    } catch (err) {
        console.error('Send failed:', err);
        alert('Failed to send message');
    } finally {
        sendBtn.disabled = false;
        messageInput.disabled = false;
        messageInput.focus();
    }
});

// Settings functions
async function loadConfig() {
    try {
        const res = await fetch('/config');
        currentConfig = await res.json();
        applyConfig(currentConfig);
    } catch (err) {
        console.error('Failed to load config:', err);
    }
}

function applyConfig(config) {
    // Apply custom CSS
    if (customCssStyle) {
        customCssStyle.textContent = config.custom_css || '';
    }
}

async function openSettings() {
    // Populate form with current values
    settingPreventSleep.checked = currentConfig.prevent_sleep || false;
    settingVimBindings.checked = currentConfig.vim_bindings || false;
    settingCustomCss.value = currentConfig.custom_css || '';
    settingsModal.classList.remove('hidden');

    // Fetch health status for about section
    await updateHealthStatus();
}

async function updateHealthStatus() {
    const statusDb = document.getElementById('status-db');
    const statusFfmpeg = document.getElementById('status-ffmpeg');

    try {
        const res = await fetch('/health');
        const health = await res.json();

        if (health.database_accessible) {
            statusDb.textContent = 'Connected';
            statusDb.className = 'status-value ok';
        } else {
            statusDb.textContent = 'Not accessible';
            statusDb.className = 'status-value error';
        }

        if (health.ffmpeg_available) {
            statusFfmpeg.textContent = 'Available';
            statusFfmpeg.className = 'status-value ok';
        } else {
            statusFfmpeg.textContent = 'Not installed';
            statusFfmpeg.className = 'status-value warning';
        }
    } catch (err) {
        statusDb.textContent = 'Error';
        statusDb.className = 'status-value error';
        statusFfmpeg.textContent = 'Error';
        statusFfmpeg.className = 'status-value error';
    }
}

function closeSettings() {
    settingsModal.classList.add('hidden');
}

async function saveSettings() {
    const updates = {
        prevent_sleep: settingPreventSleep.checked,
        vim_bindings: settingVimBindings.checked,
        custom_css: settingCustomCss.value
    };

    try {
        const res = await fetch('/config', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates)
        });
        if (res.ok) {
            currentConfig = await res.json();
            applyConfig(currentConfig);
            closeSettings();
        } else {
            const err = await res.json();
            alert('Failed to save settings: ' + (err.detail || 'Unknown error'));
        }
    } catch (err) {
        console.error('Failed to save settings:', err);
        alert('Failed to save settings');
    }
}

// Settings event listeners
settingsBtn.addEventListener('click', openSettings);
settingsClose.addEventListener('click', closeSettings);
settingsCancel.addEventListener('click', closeSettings);
settingsSave.addEventListener('click', saveSettings);

// Close modal on backdrop click
settingsModal.querySelector('.modal-backdrop').addEventListener('click', closeSettings);

// Close modal on Escape key
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !settingsModal.classList.contains('hidden')) {
        closeSettings();
    }
});

// Initial load
loadConfig();
loadChats();
