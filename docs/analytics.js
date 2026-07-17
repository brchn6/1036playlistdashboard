/**
 * Analytics tracking for Radio Playlist Dashboard
 * Lightweight, privacy-focused analytics using Supabase
 */

(function() {
    'use strict';

    // Supabase config
    const SUPABASE_URL = 'https://ktewdeaegtukbosrgxmw.supabase.co';
    const SUPABASE_ANON_KEY = 'sb_publishable_NilIf6Wf_2_sLehnVltn6g_gZtUPsc5';

    // Generate unique session ID
    function generateSessionId() {
        return 'sess_' + Math.random().toString(36).substr(2, 9) + '_' + Date.now();
    }

    // Get or create session ID (persists for the tab session)
    function getSessionId() {
        if (!window._analyticsSessionId) {
            window._analyticsSessionId = generateSessionId();
        }
        return window._analyticsSessionId;
    }

    // Send analytics event to Supabase
    async function sendEvent(eventType, eventData = {}) {
        console.log('[analytics] sending event:', eventType);
        try {
            const sessionId = getSessionId();
            
            const payload = {
                session_id: sessionId,
                event_type: eventType,
                event_data: eventData,
                user_agent: navigator.userAgent,
                referrer: document.referrer || null,
                screen_width: window.screen.width,
                screen_height: window.screen.height,
                language: navigator.language
            };

            console.log('[analytics] payload:', payload);

            // Send to Supabase directly (no external IP lookup - privacy first)
            const response = await fetch(`${SUPABASE_URL}/rest/v1/analytics_events`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'apikey': SUPABASE_ANON_KEY,
                    'Authorization': `Bearer ${SUPABASE_ANON_KEY}`,
                    'Prefer': 'return=minimal'
                },
                body: JSON.stringify(payload)
            });

            console.log('[analytics] response status:', response.status);
            if (!response.ok) {
                const errorText = await response.text();
                console.warn('[analytics] send failed:', response.status, errorText);
            } else {
                console.log('[analytics] event sent successfully');
            }
        } catch (error) {
            // Silently fail - don't break the site
            console.warn('[analytics] error:', error);
        }
    }

    // Track page view
    function trackPageView() {
        sendEvent('page_view', {
            path: window.location.pathname,
            hash: window.location.hash,
            timestamp: new Date().toISOString()
        });
    }

    // Track tab clicks
    function trackTabClick(tabName) {
        sendEvent('tab_click', {
            tab: tabName,
            timestamp: new Date().toISOString()
        });
    }

    // Track session duration
    function trackSessionEnd() {
        const startTime = window._analyticsStartTime || Date.now();
        const duration = Math.round((Date.now() - startTime) / 1000); // seconds
        
        sendEvent('session_end', {
            duration_seconds: duration,
            timestamp: new Date().toISOString()
        });
    }

    // Initialize
    window._analyticsStartTime = Date.now();
    
    // Track page view on load
    trackPageView();

    // Track session end when user leaves
    window.addEventListener('beforeunload', trackSessionEnd);

    // Expose tracking functions globally
    window.RadioAnalytics = {
        trackTabClick: trackTabClick,
        sendEvent: sendEvent
    };

    // Hook into tab clicks (assuming tabs have data-tab attribute or similar)
    document.addEventListener('DOMContentLoaded', function() {
        // Find all tab buttons/links
        const tabButtons = document.querySelectorAll('[data-tab], .tab-button, [role="tab"]');
        tabButtons.forEach(button => {
            button.addEventListener('click', function() {
                const tabName = this.getAttribute('data-tab') || 
                               this.getAttribute('aria-controls') || 
                               this.textContent.trim();
                trackTabClick(tabName);
            });
        });
    });

})();
