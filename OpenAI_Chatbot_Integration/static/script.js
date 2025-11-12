// =====================================
// DOM Elements
// =====================================

const chatForm = document.getElementById('chatForm');
const userInput = document.getElementById('userInput');
const chatMessages = document.getElementById('chatMessages');
const sendButton = document.getElementById('sendButton');

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
 * Send query to the Flask backend
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
// Initialization
// =====================================

/**
 * Initialize the application
 */
function init() {
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

