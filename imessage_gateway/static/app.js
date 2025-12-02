const chatList = document.getElementById('chat-list');
const chatTitle = document.getElementById('chat-title');
const messagesDiv = document.getElementById('messages');
const sendForm = document.getElementById('send-form');
const messageInput = document.getElementById('message-input');
const sendBtn = document.getElementById('send-btn');

let currentChatId = null;
let currentRecipient = null;
let pollInterval = null;
let lastMessageId = 0;

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
    loadMessages();
    startPolling();
}

async function loadMessages() {
    if (!currentChatId) return;
    try {
        let url = `/messages?chat_id=${currentChatId}&limit=100`;
        const res = await fetch(url);
        const messages = await res.json();
        renderMessages(messages);
        if (messages.length > 0) {
            lastMessageId = Math.max(...messages.map(m => m.rowid));
        }
    } catch (err) {
        console.error('Failed to load messages:', err);
        messagesDiv.innerHTML = '<div class="empty-state">Failed to load messages</div>';
    }
}

async function pollNewMessages() {
    if (!currentChatId) return;
    try {
        const url = `/messages?chat_id=${currentChatId}&limit=50&after_rowid=${lastMessageId}`;
        const res = await fetch(url);
        const messages = await res.json();
        if (messages.length > 0) {
            appendMessages(messages);
            lastMessageId = Math.max(...messages.map(m => m.rowid));
        }
    } catch (err) {
        console.error('Poll failed:', err);
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

function appendMessages(messages) {
    const sorted = [...messages].sort((a, b) => a.rowid - b.rowid);
    const emptyState = messagesDiv.querySelector('.empty-state');
    if (emptyState) emptyState.remove();
    sorted.forEach(msg => {
        messagesDiv.insertAdjacentHTML('beforeend', messageHtml(msg));
    });
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
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
    return `
        <div class="message ${cls}">
            <div class="text">${escapeHtml(text)}</div>
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

function startPolling() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(pollNewMessages, 3000);
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
            // Poll immediately to show sent message
            setTimeout(pollNewMessages, 500);
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

// Initial load
loadChats();
