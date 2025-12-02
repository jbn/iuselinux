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
    // Prefer identifier (phone/email) for 1:1 chats, or display_name for group chats
    // Skip display_name if it looks like a guid (starts with "chat" followed by digits)
    const guidPattern = /^chat\d+$/;
    const hasValidDisplayName = chat.display_name && !guidPattern.test(chat.display_name);
    return chat.identifier || (hasValidDisplayName ? chat.display_name : null) || 'Unknown';
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

function renderMessages(messages) {
    if (messages.length === 0) {
        messagesDiv.innerHTML = '<div class="empty-state">No messages</div>';
        return;
    }
    // Messages come newest first, reverse for display
    const sorted = [...messages].sort((a, b) => a.rowid - b.rowid);
    messagesDiv.innerHTML = sorted.map(messageHtml).join('');
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

function messageHtml(msg) {
    const cls = msg.is_from_me ? 'from-me' : 'from-them';
    const text = msg.text || '';
    const time = msg.timestamp ? formatTime(msg.timestamp) : '';
    return `
        <div class="message ${cls}">
            <div class="text">${escapeHtml(text)}</div>
            <div class="timestamp">${time}</div>
        </div>
    `;
}

function formatTime(isoString) {
    const d = new Date(isoString);
    return d.toLocaleString();
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
