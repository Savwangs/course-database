// =====================================
// DOM Elements
// =====================================

const chatForm = document.getElementById('chatForm');
const userInput = document.getElementById('userInput');
const chatMessages = document.getElementById('chatMessages');
const sendButton = document.getElementById('sendButton');
const clearButton = document.getElementById('clearButton');
const conversationBadge = document.getElementById('conversationBadge');
const exchangeCount = document.getElementById('exchangeCount');

// =====================================
// Utility Functions
// =====================================

/**
 * Scroll chat to the bottom smoothly
 */
function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

/**
 * Auto-resize textarea based on content
 */
function autoResizeTextarea() {
    userInput.style.height = 'auto';
    userInput.style.height = Math.min(userInput.scrollHeight, 150) + 'px';
}

/**
 * Create a message element
 * @param {string} text - The message text
 * @param {boolean} isUser - Whether this is a user message
 * @returns {HTMLElement} The message element
 */
function createMessage(text, isUser = false) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${isUser ? 'user-message' : 'assistant-message'}`;
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = isUser ? '👤' : '🤖';
    
    const content = document.createElement('div');
    content.className = 'message-content';
    
    const messageText = document.createElement('div');
    messageText.className = 'message-text';
    
    // Parse markdown if it's an assistant message
    if (!isUser && typeof marked !== 'undefined') {
        messageText.innerHTML = marked.parse(text);
    } else {
        messageText.innerHTML = escapeHtml(text).replace(/\n/g, '<br>');
    }
    
    content.appendChild(messageText);
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(content);
    
    return messageDiv;
}

/**
 * Create a loading indicator
 * @returns {HTMLElement} The loading element
 */
function createLoadingIndicator() {
    const loadingDiv = document.createElement('div');
    loadingDiv.className = 'loading-message';
    loadingDiv.id = 'loadingIndicator';
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = '🤖';
    
    const content = document.createElement('div');
    content.className = 'message-content';
    
    const messageText = document.createElement('div');
    messageText.className = 'message-text';
    
    const typingIndicator = document.createElement('div');
    typingIndicator.className = 'typing-indicator';
    
    for (let i = 0; i < 3; i++) {
        const dot = document.createElement('div');
        dot.className = 'typing-dot';
        typingIndicator.appendChild(dot);
    }
    
    const text = document.createElement('span');
    text.textContent = 'Thinking';
    text.style.marginLeft = '8px';
    
    messageText.appendChild(typingIndicator);
    messageText.appendChild(text);
    content.appendChild(messageText);
    loadingDiv.appendChild(avatar);
    loadingDiv.appendChild(content);
    
    return loadingDiv;
}

/**
 * Escape HTML to prevent XSS
 * @param {string} text - Text to escape
 * @returns {string} Escaped text
 */
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

/**
 * Show error message to user
 * @param {string} errorText - Error message
 */
function showError(errorText) {
    const errorMessage = createMessage(
        `❌ ${errorText}\n\nPlease try again or rephrase your question.`,
        false
    );
    chatMessages.appendChild(errorMessage);
    scrollToBottom();
}

// =====================================
// API Communication
// =====================================

/**
 * Update conversation status badge
 */
async function updateConversationStatus() {
    try {
        const response = await fetch('/conversation/status');
        const data = await response.json();
        
        if (data.success && data.has_history) {
            conversationBadge.style.display = 'flex';
            exchangeCount.textContent = data.exchange_count;
        } else {
            conversationBadge.style.display = 'none';
        }
    } catch (error) {
        console.error('Error updating conversation status:', error);
    }
}

/**
 * Send query to the Flask backend with conversation memory
 * @param {string} query - User's question
 */
async function sendQuery(query) {
    // Disable input while processing
    sendButton.disabled = true;
    userInput.disabled = true;
    
    // Add user message to chat
    const userMessage = createMessage(query, true);
    chatMessages.appendChild(userMessage);
    scrollToBottom();
    
    // Show loading indicator
    const loadingIndicator = createLoadingIndicator();
    chatMessages.appendChild(loadingIndicator);
    scrollToBottom();
    
    try {
        // Send request to Flask backend
        const response = await fetch('/ask', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ query: query })
        });
        
        // Remove loading indicator
        loadingIndicator.remove();
        
        if (!response.ok) {
            throw new Error(`Server error: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data.success) {
            // Add assistant response
            const assistantMessage = createMessage(data.response, false);
            chatMessages.appendChild(assistantMessage);
            
            // Update conversation status badge
            await updateConversationStatus();
        } else {
            showError(data.error || 'Failed to get response');
        }
        
    } catch (error) {
        console.error('Error:', error);
        loadingIndicator.remove();
        showError('Unable to connect to the server. Please check your connection and try again.');
    } finally {
        // Re-enable input
        sendButton.disabled = false;
        userInput.disabled = false;
        userInput.focus();
        scrollToBottom();
    }
}

/**
 * Clear conversation history
 */
async function clearConversation() {
    if (!confirm('Are you sure you want to clear the conversation history? This will start a new conversation.')) {
        return;
    }
    
    try {
        const response = await fetch('/clear', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        });
        
        const data = await response.json();
        
        if (data.success) {
            // Clear chat messages (keep welcome message)
            const welcomeMessage = chatMessages.querySelector('.message');
            chatMessages.innerHTML = '';
            if (welcomeMessage) {
                chatMessages.appendChild(welcomeMessage);
            }
            
            // Update conversation status
            await updateConversationStatus();
            
            // Show success message
            const notificationDiv = document.createElement('div');
            notificationDiv.className = 'message assistant-message';
            notificationDiv.innerHTML = `
                <div class="message-avatar">🔄</div>
                <div class="message-content">
                    <div class="message-text" style="background: rgba(16, 185, 129, 0.15); border-color: rgba(16, 185, 129, 0.3);">
                        <p>✅ Conversation cleared! Starting fresh.</p>
                    </div>
                </div>
            `;
            chatMessages.appendChild(notificationDiv);
            scrollToBottom();
            
            // Remove notification after 3 seconds
            setTimeout(() => {
                notificationDiv.style.opacity = '0';
                setTimeout(() => notificationDiv.remove(), 300);
            }, 3000);
        }
    } catch (error) {
        console.error('Error clearing conversation:', error);
        showError('Failed to clear conversation. Please try again.');
    }
}

// =====================================
// Event Handlers
// =====================================

/**
 * Handle form submission
 */
chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const query = userInput.value.trim();
    
    if (!query) {
        return;
    }
    
    // Clear input
    userInput.value = '';
    autoResizeTextarea();
    
    // Send query
    await sendQuery(query);
});

/**
 * Handle Enter key (send) vs Shift+Enter (new line)
 */
userInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        chatForm.dispatchEvent(new Event('submit'));
    }
});

/**
 * Auto-resize textarea on input
 */
userInput.addEventListener('input', autoResizeTextarea);

/**
 * Send example query when example button is clicked
 * @param {string} query - The example query text
 */
function sendExampleQuery(query) {
    userInput.value = query;
    autoResizeTextarea();
    chatForm.dispatchEvent(new Event('submit'));
}

// Make function available globally for onclick handlers
window.sendExampleQuery = sendExampleQuery;

// =====================================
// Clear Button Handler
// =====================================

if (clearButton) {
    clearButton.addEventListener('click', clearConversation);
}

// =====================================
// Initialization
// =====================================

/**
 * Initialize the application
 */
async function init() {
    // Focus on input
    userInput.focus();
    
    // Configure marked.js for better markdown rendering
    if (typeof marked !== 'undefined') {
        marked.setOptions({
            breaks: true,
            gfm: true,
            headerIds: false,
            mangle: false
        });
    }
    
    // Update conversation status on load
    await updateConversationStatus();
    
    // Check for example query from landing page
    const exampleQuery = sessionStorage.getItem('exampleQuery');
    if (exampleQuery) {
        sessionStorage.removeItem('exampleQuery');
        userInput.value = exampleQuery;
        autoResizeTextarea();
        // Auto-submit after a short delay
        setTimeout(() => {
            chatForm.dispatchEvent(new Event('submit'));
        }, 500);
    }
    
    console.log('✅ DVC Course Assistant initialized');
    console.log('💬 Conversation memory enabled - follow-up questions supported!');
}

// Run initialization when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// =====================================
// Health Check (Optional)
// =====================================

/**
 * Check if the backend is healthy
 */
async function checkHealth() {
    try {
        const response = await fetch('/health');
        const data = await response.json();
        console.log('🏥 Backend health:', data);
    } catch (error) {
        console.error('❌ Backend health check failed:', error);
    }
}

// Run health check on load
checkHealth();

