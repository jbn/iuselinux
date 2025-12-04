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
const settingApiToken = document.getElementById('setting-api-token');
const customCssStyle = document.getElementById('custom-css');

let currentChatId = null;
let currentRecipient = null;
let websocket = null;
let lastMessageId = 0;
let allMessages = [];  // Store all messages for current chat
let currentConfig = {}; // Store current configuration

// Auto-scroll state
let userHasScrolledUp = false;  // Track if user manually scrolled up
const SCROLL_THRESHOLD = 50;    // Pixels from bottom to consider "at bottom"

function isScrolledToBottom() {
    return messagesDiv.scrollHeight - messagesDiv.scrollTop - messagesDiv.clientHeight < SCROLL_THRESHOLD;
}

function scrollToBottom() {
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
    userHasScrolledUp = false;
    hideNewMessageIndicator();
}

function showNewMessageIndicator() {
    let indicator = document.getElementById('new-message-indicator');
    if (!indicator) {
        indicator = document.createElement('div');
        indicator.id = 'new-message-indicator';
        indicator.className = 'new-message-indicator';
        indicator.innerHTML = '↓ New message';
        indicator.addEventListener('click', scrollToBottom);
        messagesDiv.parentNode.appendChild(indicator);
    }
    indicator.classList.add('visible');
}

function hideNewMessageIndicator() {
    const indicator = document.getElementById('new-message-indicator');
    if (indicator) {
        indicator.classList.remove('visible');
    }
}

// Track user scroll
messagesDiv.addEventListener('scroll', () => {
    if (isScrolledToBottom()) {
        userHasScrolledUp = false;
        hideNewMessageIndicator();
    } else {
        userHasScrolledUp = true;
    }
});

// Vim mode state
let vimMode = 'insert'; // 'insert' or 'normal'
let vimEnabled = false;

// Contact cache - stores resolved contacts with expiry
const contactCache = new Map();
let contactCacheTtl = 86400; // Default 24 hours, updated from config

function getCachedContact(handle) {
    const cached = contactCache.get(handle);
    if (!cached) return null;
    if (Date.now() > cached.expiresAt) {
        contactCache.delete(handle);
        return null;
    }
    return cached.data;
}

function setCachedContact(handle, data, ttlSeconds) {
    contactCache.set(handle, {
        data: data,
        expiresAt: Date.now() + (ttlSeconds * 1000)
    });
}

async function resolveContact(handle) {
    if (!handle) return null;

    // Check cache first
    const cached = getCachedContact(handle);
    if (cached !== null) return cached;

    try {
        const res = await fetch(`/contacts/${encodeURIComponent(handle)}`);
        if (!res.ok) {
            // Cache negative result too (but shorter TTL)
            setCachedContact(handle, null, 300); // 5 min for 404s
            return null;
        }

        // Parse Cache-Control header for TTL
        const cacheControl = res.headers.get('Cache-Control') || '';
        const maxAgeMatch = cacheControl.match(/max-age=(\d+)/);
        const ttl = maxAgeMatch ? parseInt(maxAgeMatch[1]) : contactCacheTtl;

        const contact = await res.json();
        setCachedContact(handle, contact, ttl);
        return contact;
    } catch (err) {
        console.error('Failed to resolve contact:', handle, err);
        return null;
    }
}

function getContactDisplayName(contact, fallback) {
    if (contact && contact.name) {
        return contact.name;
    }
    return fallback || 'Unknown';
}

function getContactInitials(contact, fallback) {
    if (contact && contact.initials) {
        return contact.initials;
    }
    // Generate initials from fallback (phone/email)
    if (fallback) {
        if (fallback.includes('@')) {
            return fallback.charAt(0).toUpperCase();
        }
        // For phone, use last 2 digits
        const digits = fallback.replace(/\D/g, '');
        return digits.slice(-2);
    }
    return '?';
}

async function loadChats() {
    try {
        const res = await fetch('/chats?limit=100');
        const chats = await res.json();
        renderChats(chats);

        // Auto-select the first (most recent) chat if none is selected
        if (!currentChatId && chats.length > 0) {
            const firstChatItem = chatList.querySelector('.chat-item');
            if (firstChatItem) {
                selectChat(firstChatItem);
            }
        }
    } catch (err) {
        console.error('Failed to load chats:', err);
        chatList.innerHTML = '<div class="empty-state">Failed to load chats</div>';
    }
}

function getChatDisplayName(chat) {
    // For 1:1 chats, prefer contact name if available
    if (chat.contact && chat.contact.name) {
        return chat.contact.name;
    }

    // For 1:1 chats without contact, use identifier (phone/email)
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

function getChatInitials(chat) {
    if (chat.contact && chat.contact.initials) {
        return chat.contact.initials;
    }
    // Generate from identifier
    return getContactInitials(null, chat.identifier);
}

function getChatAvatarHtml(chat) {
    if (chat.contact && chat.contact.has_image && chat.contact.image_url) {
        return `<img src="${chat.contact.image_url}" alt="" class="chat-avatar-img">`;
    }
    const initials = getChatInitials(chat);
    return `<span class="chat-avatar-initials">${escapeHtml(initials)}</span>`;
}

function renderChats(chats) {
    if (chats.length === 0) {
        chatList.innerHTML = '<div class="empty-state">No chats found</div>';
        return;
    }
    chatList.innerHTML = chats.map(chat => {
        const displayName = getChatDisplayName(chat);
        const avatarHtml = getChatAvatarHtml(chat);
        // Show identifier as subtitle only if different from display name
        const subtitle = (chat.contact && chat.contact.name && chat.identifier)
            ? chat.identifier
            : '';

        // For sending: use identifier (phone/email) for 1:1 chats, guid for group chats
        // Group chats have identifiers starting with "chat" (e.g., "chat123456")
        const isGroupChat = chat.identifier && chat.identifier.startsWith('chat');
        const sendTarget = isGroupChat ? chat.guid : (chat.identifier || '');

        return `
            <div class="chat-item" data-id="${chat.rowid}" data-identifier="${chat.identifier || ''}" data-send-target="${sendTarget}">
                <div class="chat-avatar">${avatarHtml}</div>
                <div class="chat-info">
                    <div class="chat-name">${escapeHtml(displayName)}</div>
                    ${subtitle ? `<div class="chat-identifier">${escapeHtml(subtitle)}</div>` : ''}
                </div>
            </div>
        `;
    }).join('');

    chatList.querySelectorAll('.chat-item').forEach(item => {
        item.addEventListener('click', () => selectChat(item));
    });
}

function selectChat(item) {
    chatList.querySelectorAll('.chat-item').forEach(i => i.classList.remove('active'));
    item.classList.add('active');

    currentChatId = parseInt(item.dataset.id, 10);
    currentRecipient = item.dataset.sendTarget;  // Use send-target which has guid for group chats
    const name = item.querySelector('.chat-name').textContent;
    chatTitle.textContent = name;

    messageInput.disabled = !currentRecipient;
    sendBtn.disabled = !currentRecipient;
    if (!currentRecipient) {
        messageInput.placeholder = 'Cannot send (no recipient identifier)';
    } else {
        messageInput.placeholder = 'Type a message...';
    }

    // Reset scroll state for new chat
    userHasScrolledUp = false;
    hideNewMessageIndicator();

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
        renderMessages(allMessages, true);  // Force scroll on initial load
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

function renderMessages(messages, forceScroll = false) {
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

    // Scroll to bottom if forced (initial load) or if user hasn't scrolled up
    if (forceScroll || !userHasScrolledUp) {
        scrollToBottom();
    }
}

function appendMessages(newMessages) {
    // Add new messages to our collection, avoiding duplicates
    const existingIds = new Set(allMessages.map(m => m.rowid));
    let hasNewMessages = false;
    for (const msg of newMessages) {
        if (!existingIds.has(msg.rowid)) {
            allMessages.push(msg);
            hasNewMessages = true;
        }
    }

    // Re-render with all messages sorted
    renderMessages(allMessages);

    // Show indicator if new messages arrived and user is scrolled up
    if (hasNewMessages && userHasScrolledUp) {
        showNewMessageIndicator();
    }
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

function getMessageSenderHtml(msg) {
    if (msg.is_from_me) return '';

    // Get sender name from contact or handle
    const contact = msg.contact;
    const senderName = getContactDisplayName(contact, msg.handle_id);
    const initials = getContactInitials(contact, msg.handle_id);

    let avatarHtml;
    if (contact && contact.has_image && contact.image_url) {
        avatarHtml = `<img src="${contact.image_url}" alt="" class="msg-avatar-img">`;
    } else {
        avatarHtml = `<span class="msg-avatar-initials">${escapeHtml(initials)}</span>`;
    }

    return `
        <div class="message-sender">
            <div class="msg-avatar">${avatarHtml}</div>
            <span class="sender-name">${escapeHtml(senderName)}</span>
        </div>
    `;
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
    const senderHtml = getMessageSenderHtml(msg);

    // If we only have attachments and no text, don't show empty text bubble
    if (!text && attachmentsHtml) {
        return `
            <div class="message-wrapper ${cls}">
                ${senderHtml}
                <div class="message ${cls}">
                    ${attachmentsHtml}
                </div>
            </div>
        `;
    }

    return `
        <div class="message-wrapper ${cls}">
            ${senderHtml}
            <div class="message ${cls}">
                ${text ? `<div class="text">${escapeHtml(text)}</div>` : ''}
                ${attachmentsHtml}
            </div>
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
        // Remove onclose handler before closing to prevent reconnect loop
        websocket.onclose = null;
        websocket.close();
        websocket = null;
    }

    if (!currentChatId) return;

    // Build WebSocket URL
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws?chat_id=${currentChatId}`;

    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
        console.log('WebSocket connected');
        // Tell server to start from our current position
        if (lastMessageId > 0) {
            ws.send(JSON.stringify({
                type: 'set_after_rowid',
                rowid: lastMessageId
            }));
        }
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.type === 'messages' && data.data.length > 0) {
            appendMessages(data.data);
            lastMessageId = data.last_rowid;
        }
        // Ignore ping messages
    };

    ws.onclose = () => {
        console.log('WebSocket closed, reconnecting in 3s...');
        // Only reconnect if this is still our active websocket
        if (websocket === ws) {
            websocket = null;
            setTimeout(() => {
                if (currentChatId && !websocket) {
                    connectWebSocket();
                }
            }, 3000);
        }
    };

    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
    };

    websocket = ws;
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
            const errorMsg = typeof err.detail === 'string' ? err.detail : (err.detail?.msg || err.message || JSON.stringify(err.detail) || 'Unknown error');
            alert('Failed to send: ' + errorMsg);
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

    // Apply vim bindings setting
    vimEnabled = config.vim_bindings || false;
    if (vimEnabled) {
        vimMode = 'insert';
        updateVimModeIndicator();
    } else {
        removeVimModeIndicator();
    }

    // Update contact cache TTL
    contactCacheTtl = config.contact_cache_ttl || 86400;
}

async function openSettings() {
    // Populate form with current values
    settingPreventSleep.checked = currentConfig.prevent_sleep || false;
    settingVimBindings.checked = currentConfig.vim_bindings || false;
    settingCustomCss.value = currentConfig.custom_css || '';
    settingApiToken.value = currentConfig.api_token || '';
    settingsModal.classList.remove('hidden');

    // Fetch health status for about section
    await updateHealthStatus();
}

async function updateHealthStatus() {
    const statusDb = document.getElementById('status-db');
    const statusFfmpeg = document.getElementById('status-ffmpeg');
    const statusContacts = document.getElementById('status-contacts');

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

        if (statusContacts) {
            if (health.contacts_available) {
                statusContacts.textContent = 'Available';
                statusContacts.className = 'status-value ok';
            } else {
                statusContacts.textContent = 'Not available';
                statusContacts.className = 'status-value warning';
            }
        }
    } catch (err) {
        statusDb.textContent = 'Error';
        statusDb.className = 'status-value error';
        statusFfmpeg.textContent = 'Error';
        statusFfmpeg.className = 'status-value error';
        if (statusContacts) {
            statusContacts.textContent = 'Error';
            statusContacts.className = 'status-value error';
        }
    }
}

function closeSettings() {
    settingsModal.classList.add('hidden');
}

async function saveSettings() {
    const updates = {
        prevent_sleep: settingPreventSleep.checked,
        vim_bindings: settingVimBindings.checked,
        custom_css: settingCustomCss.value,
        api_token: settingApiToken.value
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
            const errorMsg = typeof err.detail === 'string' ? err.detail : (err.detail?.msg || err.message || JSON.stringify(err.detail) || 'Unknown error');
            alert('Failed to save settings: ' + errorMsg);
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

// Close modal on Escape key (but not when in vim normal mode)
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !settingsModal.classList.contains('hidden')) {
        closeSettings();
    }
});

// Vim mode implementation
function updateVimModeIndicator() {
    let indicator = document.getElementById('vim-mode-indicator');
    if (!indicator) {
        indicator = document.createElement('span');
        indicator.id = 'vim-mode-indicator';
        indicator.className = 'vim-mode-indicator';
        // Insert before the input
        messageInput.parentNode.insertBefore(indicator, messageInput);
    }
    indicator.textContent = vimMode === 'normal' ? 'NORMAL' : 'INSERT';
    indicator.className = `vim-mode-indicator vim-${vimMode}`;
}

function removeVimModeIndicator() {
    const indicator = document.getElementById('vim-mode-indicator');
    if (indicator) {
        indicator.remove();
    }
}

function handleVimKeydown(e) {
    if (!vimEnabled) return;

    const input = e.target;
    const cursorPos = input.selectionStart;
    const text = input.value;

    if (vimMode === 'normal') {
        // Prevent default for most keys in normal mode
        if (e.key.length === 1 || ['Backspace', 'Delete', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
            e.preventDefault();
        }

        switch (e.key) {
            case 'i': // Enter insert mode
                vimMode = 'insert';
                updateVimModeIndicator();
                break;
            case 'a': // Enter insert mode after cursor
                vimMode = 'insert';
                input.setSelectionRange(cursorPos + 1, cursorPos + 1);
                updateVimModeIndicator();
                break;
            case 'A': // Enter insert mode at end
                vimMode = 'insert';
                input.setSelectionRange(text.length, text.length);
                updateVimModeIndicator();
                break;
            case 'I': // Enter insert mode at beginning
                vimMode = 'insert';
                input.setSelectionRange(0, 0);
                updateVimModeIndicator();
                break;
            case 'h': // Move left
            case 'ArrowLeft':
                input.setSelectionRange(Math.max(0, cursorPos - 1), Math.max(0, cursorPos - 1));
                break;
            case 'l': // Move right
            case 'ArrowRight':
                input.setSelectionRange(Math.min(text.length, cursorPos + 1), Math.min(text.length, cursorPos + 1));
                break;
            case '0': // Go to start
            case 'Home':
                input.setSelectionRange(0, 0);
                break;
            case '$': // Go to end
            case 'End':
                input.setSelectionRange(text.length, text.length);
                break;
            case 'w': // Move to next word
                const nextWord = text.slice(cursorPos).search(/\s\S/);
                if (nextWord >= 0) {
                    input.setSelectionRange(cursorPos + nextWord + 1, cursorPos + nextWord + 1);
                } else {
                    input.setSelectionRange(text.length, text.length);
                }
                break;
            case 'b': // Move to previous word
                const beforeCursor = text.slice(0, cursorPos);
                const prevWord = beforeCursor.search(/\S\s*$/);
                if (prevWord >= 0) {
                    const wordStart = beforeCursor.slice(0, prevWord).search(/\s\S*$/);
                    input.setSelectionRange(wordStart >= 0 ? wordStart + 1 : 0, wordStart >= 0 ? wordStart + 1 : 0);
                } else {
                    input.setSelectionRange(0, 0);
                }
                break;
            case 'x': // Delete character under cursor
                if (cursorPos < text.length) {
                    input.value = text.slice(0, cursorPos) + text.slice(cursorPos + 1);
                    input.setSelectionRange(cursorPos, cursorPos);
                }
                break;
            case 'd':
                // Would need to track for dd, dw, etc. - simplified for now
                break;
            case 'D': // Delete to end of line
                input.value = text.slice(0, cursorPos);
                input.setSelectionRange(cursorPos, cursorPos);
                break;
            case 'c':
                // Would need to track for cc, cw, etc. - simplified for now
                break;
            case 'C': // Change to end of line
                input.value = text.slice(0, cursorPos);
                vimMode = 'insert';
                updateVimModeIndicator();
                break;
        }
    } else if (vimMode === 'insert') {
        if (e.key === 'Escape') {
            e.preventDefault();
            vimMode = 'normal';
            // Move cursor back one position (vim behavior)
            if (cursorPos > 0) {
                input.setSelectionRange(cursorPos - 1, cursorPos - 1);
            }
            updateVimModeIndicator();
        }
    }
}

// Attach vim keydown handler to message input
messageInput.addEventListener('keydown', handleVimKeydown);

// Initial load
loadConfig();
loadChats();
