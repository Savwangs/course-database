// =====================================
// Spotlight Effect (Aceternity-inspired)
// =====================================

const spotlight = document.getElementById('spotlight');
let mouseX = 0;
let mouseY = 0;
let currentX = 0;
let currentY = 0;
const speed = 0.1; // Smooth follow speed

// Track mouse movement
document.addEventListener('mousemove', (e) => {
    mouseX = e.clientX;
    mouseY = e.clientY;
});

// Smooth animation loop
function animateSpotlight() {
    // Smooth interpolation
    currentX += (mouseX - currentX) * speed;
    currentY += (mouseY - currentY) * speed;
    
    // Update CSS custom properties
    document.documentElement.style.setProperty('--mouse-x', `${currentX}px`);
    document.documentElement.style.setProperty('--mouse-y', `${currentY}px`);
    
    requestAnimationFrame(animateSpotlight);
}

// Start animation
animateSpotlight();

// =====================================
// Smooth Scroll for Anchor Links
// =====================================

document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});

// =====================================
// Intersection Observer for Fade-in Animations
// =====================================

const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
};

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.style.opacity = '1';
            entry.target.style.transform = 'translateY(0)';
        }
    });
}, observerOptions);

// Observe feature cards and other elements
document.querySelectorAll('.feature-card, .step-item, .example-card').forEach(el => {
    el.style.opacity = '0';
    el.style.transform = 'translateY(30px)';
    el.style.transition = 'opacity 0.6s ease-out, transform 0.6s ease-out';
    observer.observe(el);
});

// =====================================
// Example Card Click Handler
// =====================================

document.querySelectorAll('.example-card').forEach(card => {
    card.addEventListener('click', () => {
        const exampleText = card.querySelector('.example-text').textContent;
        
        // Store the example query in sessionStorage
        sessionStorage.setItem('exampleQuery', exampleText);
        
        // Navigate to chatbot
        window.location.href = '/chatbot';
    });
});

// =====================================
// Parallax Effect for Hero Visual
// =====================================

window.addEventListener('scroll', () => {
    const scrolled = window.pageYOffset;
    const heroVisual = document.querySelector('.hero-visual');
    
    if (heroVisual) {
        heroVisual.style.transform = `translateY(${scrolled * 0.3}px)`;
    }
});

// =====================================
// Dynamic Stats Counter Animation
// =====================================

function animateCounter(element, target, suffix = '') {
    const duration = 2000; // 2 seconds
    const start = 0;
    const increment = target / (duration / 16); // 60fps
    let current = start;
    
    const timer = setInterval(() => {
        current += increment;
        if (current >= target) {
            current = target;
            clearInterval(timer);
        }
        
        // Format the number
        let displayValue = Math.floor(current);
        if (suffix === '+' && displayValue > 0) {
            element.textContent = displayValue + suffix;
        } else {
            element.textContent = displayValue + suffix;
        }
    }, 16);
}

// Animate stats when they come into view
const statsObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting && !entry.target.dataset.animated) {
            entry.target.dataset.animated = 'true';
            
            const statNumbers = entry.target.querySelectorAll('.stat-number');
            statNumbers.forEach(stat => {
                const text = stat.textContent;
                if (text.includes('1000+')) {
                    stat.textContent = '0+';
                    animateCounter(stat, 1000, '+');
                } else if (text.includes('24/7')) {
                    // No animation for 24/7
                } else if (text === '5') {
                    stat.textContent = '0';
                    animateCounter(stat, 5);
                }
            });
        }
    });
}, { threshold: 0.5 });

const statsContainer = document.querySelector('.stats-container');
if (statsContainer) {
    statsObserver.observe(statsContainer);
}

// =====================================
// Button Ripple Effect
// =====================================

document.querySelectorAll('.cta-button').forEach(button => {
    button.addEventListener('click', function(e) {
        const ripple = document.createElement('span');
        const rect = this.getBoundingClientRect();
        const size = Math.max(rect.width, rect.height);
        const x = e.clientX - rect.left - size / 2;
        const y = e.clientY - rect.top - size / 2;
        
        ripple.style.cssText = `
            position: absolute;
            width: ${size}px;
            height: ${size}px;
            left: ${x}px;
            top: ${y}px;
            background: rgba(255, 255, 255, 0.5);
            border-radius: 50%;
            transform: scale(0);
            animation: ripple 0.6s ease-out;
            pointer-events: none;
        `;
        
        this.appendChild(ripple);
        
        setTimeout(() => ripple.remove(), 600);
    });
});

// Add ripple animation
const style = document.createElement('style');
style.textContent = `
    @keyframes ripple {
        to {
            transform: scale(2);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// =====================================
// Feature Card Tilt Effect
// =====================================

document.querySelectorAll('.feature-card').forEach(card => {
    card.addEventListener('mousemove', (e) => {
        const rect = card.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        
        const centerX = rect.width / 2;
        const centerY = rect.height / 2;
        
        const rotateX = (y - centerY) / 10;
        const rotateY = (centerX - x) / 10;
        
        card.style.transform = `perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateY(-5px)`;
    });
    
    card.addEventListener('mouseleave', () => {
        card.style.transform = 'perspective(1000px) rotateX(0) rotateY(0) translateY(0)';
    });
});

// =====================================
// Gradient Text Animation
// =====================================

const gradientTexts = document.querySelectorAll('.hero-title-gradient');
gradientTexts.forEach(text => {
    let hue = 0;
    setInterval(() => {
        hue = (hue + 1) % 360;
        // Subtle color shift
    }, 50);
});

// =====================================
// Loading Animation
// =====================================

window.addEventListener('load', () => {
    document.body.classList.add('loaded');
    
    // Remove loading class after animation
    setTimeout(() => {
        document.body.style.opacity = '1';
    }, 100);
});

// =====================================
// CTA Button Enhanced Hover Effect
// =====================================

document.querySelectorAll('.cta-primary').forEach(button => {
    button.addEventListener('mouseenter', function(e) {
        const rect = this.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        
        this.style.setProperty('--mouse-x', `${x}px`);
        this.style.setProperty('--mouse-y', `${y}px`);
    });
});

// =====================================
// Keyboard Navigation Enhancement
// =====================================

// Add focus visible styles for accessibility
document.addEventListener('keydown', (e) => {
    if (e.key === 'Tab') {
        document.body.classList.add('keyboard-nav');
    }
});

document.addEventListener('mousedown', () => {
    document.body.classList.remove('keyboard-nav');
});

// =====================================
// Performance Optimization
// =====================================

// Debounce scroll events
let scrollTimeout;
window.addEventListener('scroll', () => {
    if (scrollTimeout) {
        window.cancelAnimationFrame(scrollTimeout);
    }
    
    scrollTimeout = window.requestAnimationFrame(() => {
        // Scroll-based animations go here
    });
}, { passive: true });

// =====================================
// Console Message
// =====================================

console.log('%c🎓 DVC Course Assistant', 'font-size: 24px; font-weight: bold; color: #6366f1;');
console.log('%cWelcome! Built with ❤️ for DVC students', 'font-size: 14px; color: #94a3b8;');
console.log('%cPowered by OpenAI GPT-4', 'font-size: 12px; color: #cbd5e1;');

// =====================================
// Initialization
// =====================================

document.addEventListener('DOMContentLoaded', () => {
    console.log('✅ Landing page initialized');
    
    // Add any initialization code here
    
    // Preload chatbot page for faster navigation
    const chatbotLink = document.createElement('link');
    chatbotLink.rel = 'prefetch';
    chatbotLink.href = '/chatbot';
    document.head.appendChild(chatbotLink);
});

