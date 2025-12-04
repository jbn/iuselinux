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
const settingTheme = document.getElementById('setting-theme');
const customCssStyle = document.getElementById('custom-css');

let currentChatId = null;
let currentRecipient = null;
let websocket = null;
let lastMessageId = 0;
let oldestMessageId = null;  // Track oldest message for backward pagination
let allMessages = [];  // Store all messages for current chat
let currentConfig = {}; // Store current configuration
let allChats = [];  // Store all chats for reordering

// Pagination state
const PAGE_SIZE = 20;
let isLoadingOlder = false;
let hasMoreOlderMessages = true;

// Auto-scroll state
let userHasScrolledUp = false;  // Track if user manually scrolled up
const SCROLL_THRESHOLD = 50;    // Pixels from bottom to consider "at bottom"

// Notification state
let notificationsEnabled = true;  // Default on

// Theme state
let currentTheme = 'auto';  // 'auto', 'light', or 'dark'

// Optimistic message state
let pendingMessages = [];  // Messages being sent (not yet confirmed)
let pendingMessageId = -1;  // Decreasing negative IDs for pending messages

function applyTheme(theme) {
    currentTheme = theme;

    if (theme === 'auto') {
        // Remove data-theme to let CSS use :root (which doesn't have data-theme)
        // but we need to check system preference
        const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
        document.documentElement.setAttribute('data-theme', prefersDark ? 'dark' : 'light');
    } else {
        document.documentElement.setAttribute('data-theme', theme);
    }
}

// Listen for system theme changes when in auto mode
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
    if (currentTheme === 'auto') {
        document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
    }
});

// Apply theme early (before config loads) using localStorage fallback
(function() {
    const savedTheme = localStorage.getItem('theme') || 'auto';
    applyTheme(savedTheme);
})();

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

// Loading indicator for pagination
function showLoadingOlder() {
    let loader = document.getElementById('loading-older');
    if (!loader) {
        loader = document.createElement('div');
        loader.id = 'loading-older';
        loader.className = 'loading-older';
        loader.innerHTML = 'Loading older messages...';
        messagesDiv.insertBefore(loader, messagesDiv.firstChild);
    }
    loader.classList.add('visible');
}

function hideLoadingOlder() {
    const loader = document.getElementById('loading-older');
    if (loader) {
        loader.classList.remove('visible');
    }
}

// Track user scroll - detect when scrolled to top for pagination
messagesDiv.addEventListener('scroll', () => {
    if (isScrolledToBottom()) {
        userHasScrolledUp = false;
        hideNewMessageIndicator();
    } else {
        userHasScrolledUp = true;
    }

    // Load older messages when scrolled near top
    if (messagesDiv.scrollTop < 100 && !isLoadingOlder && hasMoreOlderMessages && currentChatId) {
        loadOlderMessages();
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
        allChats = chats;
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

    // Show participants for group chats - prefer resolved contact names
    if (chat.participant_contacts && chat.participant_contacts.length > 0) {
        const formatted = chat.participant_contacts.map(p => {
            // Prefer contact name if available
            if (p.contact && p.contact.name) {
                return p.contact.name;
            }
            // Fall back to handle with privacy formatting
            if (p.handle.startsWith('+') && p.handle.length > 4) {
                return '...' + p.handle.slice(-4);
            }
            return p.handle;
        });
        return formatted.join(' & ');
    }

    // Fallback to raw participants (backwards compatibility)
    if (chat.participants && chat.participants.length > 0) {
        const formatted = chat.participants.map(p => {
            if (p.startsWith('+') && p.length > 4) {
                return '...' + p.slice(-4);
            }
            return p;
        });
        return formatted.join(' & ');
    }

    return 'Unknown';
}

// Format timestamp for sidebar (iMessage style)
function formatSidebarTime(isoString) {
    if (!isoString) return '';
    const date = new Date(isoString);
    const now = new Date();
    const diffMs = now - date;
    const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

    // Today: show time
    if (date.toDateString() === now.toDateString()) {
        return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }

    // Yesterday
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    if (date.toDateString() === yesterday.toDateString()) {
        return 'Yesterday';
    }

    // Within the last week: show day name
    if (diffDays < 7) {
        return date.toLocaleDateString([], { weekday: 'long' });
    }

    // Older: show date
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

// Get first letter of a name for initials (or empty if no valid letter)
function getFirstLetter(name) {
    if (!name) return '';
    // Find the first letter character
    const match = name.match(/[a-zA-Z]/);
    return match ? match[0].toUpperCase() : '';
}

// Person icon SVG for unknown contacts
const PERSON_ICON_SVG = `<svg class="chat-avatar-icon" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>
</svg>`;

const PERSON_ICON_SMALL_SVG = `<svg class="group-avatar-icon" viewBox="0 0 24 24" fill="currentColor">
    <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>
</svg>`;

// Check if chat is a group chat
function isGroupChat(chat) {
    return chat.participants && chat.participants.length > 1;
}

function getChatInitials(chat) {
    // For contacts with a name, use first letter
    if (chat.contact && chat.contact.name) {
        return getFirstLetter(chat.contact.name);
    }
    // For display name
    if (chat.display_name) {
        const letter = getFirstLetter(chat.display_name);
        if (letter) return letter;
    }
    // No valid letter found
    return '';
}

// Get avatar content for a single participant (used in group avatars)
function getParticipantAvatarHtml(participant, small = false) {
    const imgClass = small ? 'group-avatar-img' : 'chat-avatar-img';
    const initialsClass = small ? 'group-avatar-initials' : 'chat-avatar-initials';
    const iconSvg = small ? PERSON_ICON_SMALL_SVG : PERSON_ICON_SVG;

    // Has contact photo
    if (participant.contact && participant.contact.has_image && participant.contact.image_url) {
        return `<img src="${participant.contact.image_url}" alt="" class="${imgClass}">`;
    }

    // Has contact name - use first letter
    if (participant.contact && participant.contact.name) {
        const letter = getFirstLetter(participant.contact.name);
        if (letter) {
            return `<span class="${initialsClass}">${escapeHtml(letter)}</span>`;
        }
    }

    // Unknown - show person icon
    return iconSvg;
}

function getChatAvatarHtml(chat) {
    // Group chat - show overlapping circles
    if (isGroupChat(chat) && chat.participant_contacts && chat.participant_contacts.length >= 2) {
        const p1 = chat.participant_contacts[0];
        const p2 = chat.participant_contacts[1];
        return `
            <div class="chat-avatar-group">
                <div class="group-avatar">${getParticipantAvatarHtml(p1, true)}</div>
                <div class="group-avatar">${getParticipantAvatarHtml(p2, true)}</div>
            </div>
        `;
    }

    // 1:1 chat with contact photo
    if (chat.contact && chat.contact.has_image && chat.contact.image_url) {
        return `<div class="chat-avatar"><img src="${chat.contact.image_url}" alt="" class="chat-avatar-img"></div>`;
    }

    // 1:1 chat with contact name - use first letter
    const initials = getChatInitials(chat);
    if (initials) {
        return `<div class="chat-avatar"><span class="chat-avatar-initials">${escapeHtml(initials)}</span></div>`;
    }

    // Unknown - show person icon
    return `<div class="chat-avatar">${PERSON_ICON_SVG}</div>`;
}

function renderChats(chats) {
    if (chats.length === 0) {
        chatList.innerHTML = '<div class="empty-state">No chats found</div>';
        return;
    }
    chatList.innerHTML = chats.map(chat => {
        const displayName = getChatDisplayName(chat);
        const avatarHtml = getChatAvatarHtml(chat);
        const timeStr = formatSidebarTime(chat.last_message_time);

        // Format message preview
        let preview = chat.last_message_text || '';
        if (chat.last_message_is_from_me && preview) {
            preview = 'You: ' + preview;
        }

        // For sending: use identifier (phone/email) for 1:1 chats, guid for group chats
        // Group chats have identifiers starting with "chat" (e.g., "chat123456")
        const isGroup = chat.identifier && chat.identifier.startsWith('chat');
        const sendTarget = isGroup ? chat.guid : (chat.identifier || '');
        const isActive = chat.rowid === currentChatId;

        return `
            <div class="chat-item${isActive ? ' active' : ''}" data-id="${chat.rowid}" data-identifier="${chat.identifier || ''}" data-send-target="${sendTarget}">
                ${avatarHtml}
                <div class="chat-info">
                    <div class="chat-info-top">
                        <div class="chat-name">${escapeHtml(displayName)}</div>
                        <span class="chat-time">${escapeHtml(timeStr)}</span>
                    </div>
                    <div class="chat-preview">${escapeHtml(preview)}</div>
                </div>
            </div>
        `;
    }).join('');

    chatList.querySelectorAll('.chat-item').forEach(item => {
        item.addEventListener('click', () => selectChat(item));
    });
}

// Move a chat to top of list (when new message arrives)
function moveChatToTop(chatId) {
    const chatIndex = allChats.findIndex(c => c.rowid === chatId);
    if (chatIndex > 0) {
        const [chat] = allChats.splice(chatIndex, 1);
        allChats.unshift(chat);
        renderChats(allChats);
    }
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

    // Reset scroll and pagination state for new chat
    userHasScrolledUp = false;
    hideNewMessageIndicator();
    lastMessageId = 0;
    oldestMessageId = null;
    allMessages = [];
    pendingMessages = [];  // Clear pending messages when switching chats
    hasMoreOlderMessages = true;
    isLoadingOlder = false;

    loadMessages();
    connectWebSocket();
}

async function loadMessages() {
    if (!currentChatId) return;
    try {
        // Load initial page of messages (most recent PAGE_SIZE)
        let url = `/messages?chat_id=${currentChatId}&limit=${PAGE_SIZE}`;
        const res = await fetch(url);
        const messages = await res.json();
        allMessages = messages;

        // Track IDs for pagination
        if (messages.length > 0) {
            lastMessageId = Math.max(...messages.map(m => m.rowid));
            oldestMessageId = Math.min(...messages.map(m => m.rowid));
        }

        // If we got fewer messages than PAGE_SIZE, there are no more
        hasMoreOlderMessages = messages.length >= PAGE_SIZE;

        renderMessages(allMessages, true);  // Force scroll on initial load
    } catch (err) {
        console.error('Failed to load messages:', err);
        messagesDiv.innerHTML = '<div class="empty-state">Failed to load messages</div>';
    }
}

async function loadOlderMessages() {
    if (!currentChatId || !oldestMessageId || isLoadingOlder || !hasMoreOlderMessages) return;

    isLoadingOlder = true;
    showLoadingOlder();

    // Remember scroll position to maintain it after adding older messages
    const oldScrollHeight = messagesDiv.scrollHeight;

    try {
        const url = `/messages?chat_id=${currentChatId}&limit=${PAGE_SIZE}&before_rowid=${oldestMessageId}`;
        const res = await fetch(url);
        const olderMessages = await res.json();

        if (olderMessages.length > 0) {
            // Add to our collection (avoid duplicates)
            const existingIds = new Set(allMessages.map(m => m.rowid));
            for (const msg of olderMessages) {
                if (!existingIds.has(msg.rowid)) {
                    allMessages.push(msg);
                }
            }

            // Update oldest ID
            oldestMessageId = Math.min(...olderMessages.map(m => m.rowid));

            // Render and restore scroll position
            renderMessages(allMessages, false);

            // Restore scroll position (keep user at same relative position)
            const newScrollHeight = messagesDiv.scrollHeight;
            messagesDiv.scrollTop = newScrollHeight - oldScrollHeight;
        }

        // If we got fewer messages than PAGE_SIZE, there are no more
        hasMoreOlderMessages = olderMessages.length >= PAGE_SIZE;
    } catch (err) {
        console.error('Failed to load older messages:', err);
    } finally {
        isLoadingOlder = false;
        hideLoadingOlder();
    }
}

// Time gap threshold for showing timestamp separator (in minutes)
const TIMESTAMP_GAP_MINUTES = 60;

// Build tapback map: message GUID -> list of tapback reactions
function buildTapbackMap(messages) {
    const tapbackMap = new Map();
    for (const msg of messages) {
        if (msg.tapback_type && msg.associated_guid) {
            // Extract the target message GUID from associated_guid
            // Format is like "p:0/GUID" or "bp:GUID" - extract GUID part
            let targetGuid = msg.associated_guid;
            if (targetGuid.includes('/')) {
                targetGuid = targetGuid.split('/').pop();
            }
            if (targetGuid.startsWith('bp:')) {
                targetGuid = targetGuid.substring(3);
            }

            if (!tapbackMap.has(targetGuid)) {
                tapbackMap.set(targetGuid, []);
            }
            tapbackMap.get(targetGuid).push({
                type: msg.tapback_type,
                is_from_me: msg.is_from_me,
                handle_id: msg.handle_id
            });
        }
    }
    return tapbackMap;
}

function renderMessages(messages, forceScroll = false) {
    // Combine confirmed messages with pending messages
    const allMsgs = [...messages, ...pendingMessages];

    if (allMsgs.length === 0) {
        messagesDiv.innerHTML = '<div class="empty-state">No messages</div>';
        return;
    }

    // Build tapback map before rendering
    const tapbackMap = buildTapbackMap(allMsgs);

    // Messages come newest first, reverse for display
    // Pending messages (negative rowid) will sort to end due to high _sortOrder
    const sorted = [...allMsgs].sort((a, b) => (a._sortOrder || a.rowid) - (b._sortOrder || b.rowid));

    // Filter out tapbacks for participant counting
    const realMessages = sorted.filter(m => !m.tapback_type);

    // Count unique senders (excluding "from me") to determine if this is a group chat
    const uniqueSenders = new Set();
    for (const msg of realMessages) {
        if (!msg.is_from_me && msg.handle_id) {
            uniqueSenders.add(msg.handle_id);
        }
    }
    const isGroupChat = uniqueSenders.size > 1;

    let html = '';

    // Show "load more" indicator at top if there are more messages
    if (hasMoreOlderMessages) {
        html += '<div id="loading-older" class="loading-older">Scroll up for older messages</div>';
    }

    let lastTimestamp = null;
    let lastSenderId = null;  // Track the last sender to show info only on change

    for (const msg of sorted) {
        // Skip tapback messages - they're rendered as annotations on their target
        if (msg.tapback_type) {
            continue;
        }

        // Check if we need a timestamp separator
        if (msg.timestamp) {
            const msgTime = new Date(msg.timestamp);
            if (!lastTimestamp || (msgTime - lastTimestamp) > TIMESTAMP_GAP_MINUTES * 60 * 1000) {
                html += `<div class="timestamp-separator">${formatTimeSeparator(msgTime)}</div>`;
                // Reset sender after timestamp separator so we show the sender again
                lastSenderId = null;
            }
            lastTimestamp = msgTime;
        }

        // Determine if we should show sender info:
        // - Only for received messages (not from me)
        // - Only in group chats (more than one other participant)
        // - Only when the sender changes from the previous message
        const currentSenderId = msg.is_from_me ? '__me__' : (msg.handle_id || '__unknown__');
        const showSender = isGroupChat && !msg.is_from_me && currentSenderId !== lastSenderId;
        lastSenderId = currentSenderId;

        // Get tapbacks for this message
        const tapbacks = tapbackMap.get(msg.guid) || [];
        html += messageHtml(msg, tapbacks, showSender);
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
    let newChatMessage = false;  // Track if there's a non-tapback message for notifications

    for (const msg of newMessages) {
        if (!existingIds.has(msg.rowid)) {
            allMessages.push(msg);
            hasNewMessages = true;

            // Check if this message confirms a pending message (from me, matching text)
            if (msg.is_from_me && !msg.tapback_type) {
                confirmPendingMessage(msg);
            }

            // Check if this is a real message (not tapback) for notification purposes
            if (!msg.tapback_type && !msg.is_from_me) {
                newChatMessage = true;
            }
        }
    }

    // Re-render with all messages sorted
    renderMessages(allMessages);

    // Show indicator if new messages arrived and user is scrolled up
    if (hasNewMessages && userHasScrolledUp) {
        showNewMessageIndicator();
    }

    // Send browser notification for new messages if enabled
    if (newChatMessage && notificationsEnabled && document.hidden) {
        sendNotification(newMessages);
    }

    // Move this chat to top of list
    if (hasNewMessages && currentChatId) {
        moveChatToTop(currentChatId);
    }
}

// Confirm a pending message when the real one arrives from websocket
function confirmPendingMessage(confirmedMsg) {
    // Find pending message with matching text (simple heuristic)
    const pendingIdx = pendingMessages.findIndex(p =>
        p.text === confirmedMsg.text && p._pending && !p._failed
    );

    if (pendingIdx !== -1) {
        // Remove the pending message - real one is now in allMessages
        pendingMessages.splice(pendingIdx, 1);
    }
}

// Mark a pending message as failed
function markPendingFailed(pendingId) {
    const pending = pendingMessages.find(p => p._pendingId === pendingId);
    if (pending) {
        pending._pending = false;
        pending._failed = true;
        renderMessages(allMessages);
    }
}

// Retry a failed message
function retryMessage(pendingId) {
    const pending = pendingMessages.find(p => p._pendingId === pendingId);
    if (!pending) return;

    // Reset state to pending
    pending._failed = false;
    pending._pending = true;
    renderMessages(allMessages);

    // Retry the send
    sendMessageAsync(pending._recipient, pending.text, pendingId);
}

// Dismiss a failed message
function dismissFailedMessage(pendingId) {
    const idx = pendingMessages.findIndex(p => p._pendingId === pendingId);
    if (idx !== -1) {
        pendingMessages.splice(idx, 1);
        renderMessages(allMessages);
    }
}

// Add optimistic message to pending list
function addPendingMessage(text, recipient) {
    const pendingId = `pending_${pendingMessageId--}`;
    const pending = {
        rowid: pendingMessageId,  // Negative ID
        _sortOrder: Date.now(),   // Sort by time for display
        _pendingId: pendingId,
        _pending: true,
        _failed: false,
        _recipient: recipient,
        text: text,
        is_from_me: true,
        timestamp: new Date().toISOString(),
        tapback_type: null,
        attachments: []
    };
    pendingMessages.push(pending);
    renderMessages(allMessages);
    scrollToBottom();
    return pendingId;
}

// Async send that updates pending message status
async function sendMessageAsync(recipient, text, pendingId) {
    try {
        const res = await fetch('/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ recipient, message: text })
        });
        if (!res.ok) {
            const err = await res.json();
            console.error('Send failed:', err);
            markPendingFailed(pendingId);
        }
        // On success, websocket will deliver the confirmed message
        // and confirmPendingMessage will clean up
    } catch (err) {
        console.error('Send failed:', err);
        markPendingFailed(pendingId);
    }
}

// Browser notifications
function sendNotification(messages) {
    if (!('Notification' in window)) return;

    // Find first real message (not tapback)
    const realMessage = messages.find(m => !m.tapback_type && !m.is_from_me);
    if (!realMessage) return;

    if (Notification.permission === 'granted') {
        const senderName = realMessage.contact?.name || realMessage.handle_id || 'Unknown';
        const text = realMessage.text || 'New message';
        new Notification(senderName, {
            body: text.substring(0, 100),
            icon: realMessage.contact?.image_url || undefined,
            tag: 'imessage-' + currentChatId  // Replace previous notification from same chat
        });
    } else if (Notification.permission !== 'denied') {
        Notification.requestPermission();
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

// Render tapback annotations for a message
function renderTapbacks(tapbacks) {
    if (!tapbacks || tapbacks.length === 0) return '';

    // Group tapbacks by type and count
    const tapbackCounts = {};
    for (const tb of tapbacks) {
        const emoji = TAPBACK_EMOJI[tb.type] || tb.type;
        if (!tapbackCounts[emoji]) {
            tapbackCounts[emoji] = { count: 0, fromMe: false };
        }
        tapbackCounts[emoji].count++;
        if (tb.is_from_me) {
            tapbackCounts[emoji].fromMe = true;
        }
    }

    const items = Object.entries(tapbackCounts).map(([emoji, info]) => {
        const countStr = info.count > 1 ? ` ${info.count}` : '';
        const fromMeClass = info.fromMe ? ' tapback-from-me' : '';
        return `<span class="tapback-annotation${fromMeClass}">${emoji}${countStr}</span>`;
    });

    return `<div class="tapback-annotations">${items.join('')}</div>`;
}

function messageHtml(msg, tapbacks = [], showSender = false) {
    const cls = msg.is_from_me ? 'from-me' : 'from-them';

    // Add pending/failed class for optimistic messages
    const pendingCls = msg._pending ? ' pending' : '';
    const failedCls = msg._failed ? ' failed' : '';
    const statusCls = pendingCls + failedCls;

    const text = msg.text || '';
    const attachmentsHtml = renderAttachments(msg.attachments);
    const senderHtml = showSender ? getMessageSenderHtml(msg) : '';
    const tapbacksHtml = renderTapbacks(tapbacks);

    // Status indicator only for failed messages (pending just uses opacity)
    let statusHtml = '';
    if (msg._failed) {
        statusHtml = `<div class="message-status failed">
            Failed to send
            <button class="retry-btn" onclick="retryMessage('${msg._pendingId}')">Retry</button>
            <button class="dismiss-btn" onclick="dismissFailedMessage('${msg._pendingId}')">Dismiss</button>
        </div>`;
    }

    // If we only have attachments and no text, don't show empty text bubble
    if (!text && attachmentsHtml) {
        return `
            <div class="message-wrapper ${cls}${statusCls}" data-pending-id="${msg._pendingId || ''}">
                ${senderHtml}
                <div class="message ${cls}${statusCls}">
                    ${attachmentsHtml}
                    ${tapbacksHtml}
                </div>
                ${statusHtml}
            </div>
        `;
    }

    return `
        <div class="message-wrapper ${cls}${statusCls}" data-pending-id="${msg._pendingId || ''}">
            ${senderHtml}
            <div class="message ${cls}${statusCls}">
                ${text ? `<div class="text">${escapeHtml(text)}</div>` : ''}
                ${attachmentsHtml}
                ${tapbacksHtml}
            </div>
            ${statusHtml}
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

    // Optimistically add message to UI immediately
    const pendingId = addPendingMessage(text, currentRecipient);

    // Clear input right away for better UX
    messageInput.value = '';
    messageInput.focus();

    // Send in background - status updates happen via pending message state
    sendMessageAsync(currentRecipient, text, pendingId);
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

    // Apply notification setting
    notificationsEnabled = config.notifications_enabled !== false;  // Default true

    // Apply theme setting
    const theme = config.theme || 'auto';
    applyTheme(theme);
    localStorage.setItem('theme', theme);  // Cache for early loading
}

async function openSettings() {
    // Populate form with current values
    settingPreventSleep.checked = currentConfig.prevent_sleep || false;
    settingVimBindings.checked = currentConfig.vim_bindings || false;
    settingCustomCss.value = currentConfig.custom_css || '';
    settingApiToken.value = currentConfig.api_token || '';

    // Populate notification setting if element exists
    const settingNotifications = document.getElementById('setting-notifications');
    if (settingNotifications) {
        settingNotifications.checked = currentConfig.notifications_enabled !== false;
    }

    // Populate theme setting
    if (settingTheme) {
        settingTheme.value = currentConfig.theme || 'auto';
    }

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
    const settingNotifications = document.getElementById('setting-notifications');

    const updates = {
        prevent_sleep: settingPreventSleep.checked,
        vim_bindings: settingVimBindings.checked,
        custom_css: settingCustomCss.value,
        api_token: settingApiToken.value,
        notifications_enabled: settingNotifications ? settingNotifications.checked : true,
        theme: settingTheme ? settingTheme.value : 'auto'
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

// Request notification permission on load
if ('Notification' in window && Notification.permission === 'default') {
    // Don't request immediately - wait for user interaction
    document.addEventListener('click', function requestNotificationPermission() {
        if (Notification.permission === 'default') {
            Notification.requestPermission();
        }
        document.removeEventListener('click', requestNotificationPermission);
    }, { once: true });
}

// Compose Modal functionality
const composeModal = document.getElementById('compose-modal');
const composeRecipient = document.getElementById('compose-recipient');
const composeMessage = document.getElementById('compose-message');
const composeSend = document.getElementById('compose-send');
const composeCancel = document.getElementById('compose-cancel');
const composeSuggestions = document.getElementById('compose-suggestions');
const newMessageBtn = document.getElementById('new-message-btn');

let selectedRecipient = null;
let selectedSuggestionIndex = -1;
let currentSuggestions = [];

function openComposeModal() {
    composeModal.classList.remove('hidden');
    composeRecipient.value = '';
    composeMessage.value = '';
    composeSend.disabled = true;
    selectedRecipient = null;
    selectedSuggestionIndex = -1;
    currentSuggestions = [];
    composeSuggestions.classList.add('hidden');
    setTimeout(() => composeRecipient.focus(), 100);
}

function closeComposeModal() {
    composeModal.classList.add('hidden');
}

function updateComposeSendButton() {
    const hasRecipient = selectedRecipient || composeRecipient.value.trim();
    const hasMessage = composeMessage.value.trim();
    composeSend.disabled = !hasRecipient || !hasMessage;
}

// Search for contacts/chats matching the query
async function searchRecipients(query) {
    if (!query || query.length < 2) {
        composeSuggestions.classList.add('hidden');
        currentSuggestions = [];
        return;
    }

    const queryLower = query.toLowerCase();

    // Search through existing chats
    const matches = allChats.filter(chat => {
        // Match by display name
        const displayName = getChatDisplayName(chat).toLowerCase();
        if (displayName.includes(queryLower)) return true;

        // Match by identifier
        if (chat.identifier && chat.identifier.toLowerCase().includes(queryLower)) return true;

        // Match by participant names
        if (chat.participant_contacts) {
            for (const p of chat.participant_contacts) {
                if (p.contact && p.contact.name && p.contact.name.toLowerCase().includes(queryLower)) {
                    return true;
                }
                if (p.handle && p.handle.toLowerCase().includes(queryLower)) {
                    return true;
                }
            }
        }

        return false;
    }).slice(0, 8);

    currentSuggestions = matches;

    if (matches.length === 0) {
        composeSuggestions.classList.add('hidden');
        return;
    }

    renderSuggestions(matches);
    composeSuggestions.classList.remove('hidden');
}

function renderSuggestions(matches) {
    composeSuggestions.innerHTML = matches.map((chat, index) => {
        const displayName = getChatDisplayName(chat);
        const detail = chat.identifier || '';
        const isGroup = chat.identifier && chat.identifier.startsWith('chat');
        const sendTarget = isGroup ? chat.guid : (chat.identifier || '');

        // Get avatar HTML (simplified for suggestions)
        let avatarHtml;
        if (chat.contact && chat.contact.has_image && chat.contact.image_url) {
            avatarHtml = `<img src="${chat.contact.image_url}" alt="" class="suggestion-avatar-img">`;
        } else {
            const letter = getChatInitials(chat);
            if (letter) {
                avatarHtml = `<span class="suggestion-avatar-initials">${escapeHtml(letter)}</span>`;
            } else {
                avatarHtml = `<svg class="suggestion-avatar-initials" viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
                    <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>
                </svg>`;
            }
        }

        const selectedClass = index === selectedSuggestionIndex ? ' selected' : '';

        return `
            <div class="compose-suggestion${selectedClass}" data-index="${index}" data-send-target="${sendTarget}" data-display-name="${escapeHtml(displayName)}" data-chat-id="${chat.rowid}">
                <div class="suggestion-avatar">${avatarHtml}</div>
                <div class="suggestion-info">
                    <div class="suggestion-name">${escapeHtml(displayName)}</div>
                    <div class="suggestion-detail">${escapeHtml(detail)}</div>
                </div>
                <span class="suggestion-arrow">›</span>
            </div>
        `;
    }).join('');

    // Add click handlers
    composeSuggestions.querySelectorAll('.compose-suggestion').forEach(el => {
        el.addEventListener('click', () => selectSuggestion(el));
    });
}

function selectSuggestion(el) {
    const sendTarget = el.dataset.sendTarget;
    const displayName = el.dataset.displayName;
    const chatId = parseInt(el.dataset.chatId, 10);

    selectedRecipient = sendTarget;
    composeRecipient.value = displayName;
    composeSuggestions.classList.add('hidden');
    updateComposeSendButton();

    // If this is an existing chat, navigate to it instead
    if (chatId) {
        closeComposeModal();
        const chatItem = chatList.querySelector(`.chat-item[data-id="${chatId}"]`);
        if (chatItem) {
            selectChat(chatItem);
        }
    } else {
        composeMessage.focus();
    }
}

async function sendComposeMessage() {
    const recipient = selectedRecipient || composeRecipient.value.trim();
    const message = composeMessage.value.trim();

    if (!recipient || !message) return;

    composeSend.disabled = true;

    try {
        const res = await fetch('/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ recipient, message })
        });

        if (!res.ok) {
            const err = await res.json();
            const errorMsg = typeof err.detail === 'string' ? err.detail : (err.detail?.msg || err.message || JSON.stringify(err.detail) || 'Unknown error');
            alert('Failed to send: ' + errorMsg);
            composeSend.disabled = false;
            return;
        }

        // Success - close modal and refresh chats
        closeComposeModal();
        await loadChats();

    } catch (err) {
        console.error('Send failed:', err);
        alert('Failed to send message');
        composeSend.disabled = false;
    }
}

// Event listeners for compose modal
newMessageBtn.addEventListener('click', openComposeModal);
composeCancel.addEventListener('click', closeComposeModal);
composeModal.querySelector('.modal-backdrop').addEventListener('click', closeComposeModal);
composeSend.addEventListener('click', sendComposeMessage);

composeRecipient.addEventListener('input', (e) => {
    selectedRecipient = null;
    selectedSuggestionIndex = -1;
    searchRecipients(e.target.value);
    updateComposeSendButton();
});

composeMessage.addEventListener('input', updateComposeSendButton);

// Keyboard navigation for suggestions
composeRecipient.addEventListener('keydown', (e) => {
    if (currentSuggestions.length === 0) return;

    if (e.key === 'ArrowDown') {
        e.preventDefault();
        selectedSuggestionIndex = Math.min(selectedSuggestionIndex + 1, currentSuggestions.length - 1);
        renderSuggestions(currentSuggestions);
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        selectedSuggestionIndex = Math.max(selectedSuggestionIndex - 1, -1);
        renderSuggestions(currentSuggestions);
    } else if (e.key === 'Enter' && selectedSuggestionIndex >= 0) {
        e.preventDefault();
        const el = composeSuggestions.querySelector(`[data-index="${selectedSuggestionIndex}"]`);
        if (el) selectSuggestion(el);
    } else if (e.key === 'Escape') {
        composeSuggestions.classList.add('hidden');
    }
});

// Close compose modal on Escape
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !composeModal.classList.contains('hidden')) {
        closeComposeModal();
    }
});

// Sidebar resize functionality
const sidebar = document.querySelector('.sidebar');
const sidebarResize = document.getElementById('sidebar-resize');
const SIDEBAR_WIDTH_KEY = 'sidebarWidth';
const MIN_SIDEBAR_WIDTH = 200;
const MAX_SIDEBAR_WIDTH_RATIO = 0.5;

// Load saved sidebar width
(function() {
    const savedWidth = localStorage.getItem(SIDEBAR_WIDTH_KEY);
    if (savedWidth) {
        const width = parseInt(savedWidth, 10);
        if (width >= MIN_SIDEBAR_WIDTH && width <= window.innerWidth * MAX_SIDEBAR_WIDTH_RATIO) {
            sidebar.style.width = width + 'px';
        }
    }
})();

let isResizing = false;

sidebarResize.addEventListener('mousedown', (e) => {
    isResizing = true;
    sidebarResize.classList.add('dragging');
    document.body.classList.add('resizing-sidebar');
    e.preventDefault();
});

document.addEventListener('mousemove', (e) => {
    if (!isResizing) return;

    const maxWidth = window.innerWidth * MAX_SIDEBAR_WIDTH_RATIO;
    let newWidth = e.clientX;

    // Clamp to min/max
    newWidth = Math.max(MIN_SIDEBAR_WIDTH, Math.min(maxWidth, newWidth));

    sidebar.style.width = newWidth + 'px';
});

document.addEventListener('mouseup', () => {
    if (isResizing) {
        isResizing = false;
        sidebarResize.classList.remove('dragging');
        document.body.classList.remove('resizing-sidebar');

        // Save to localStorage
        const currentWidth = parseInt(sidebar.style.width, 10) || sidebar.offsetWidth;
        localStorage.setItem(SIDEBAR_WIDTH_KEY, currentWidth.toString());
    }
});

// Initial load
loadConfig();
loadChats();
