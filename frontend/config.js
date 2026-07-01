// Global Configuration
// Automatically use local backend if running locally (localhost, 127.0.0.1, or file protocol)
window.API_BASE_URL = (
    window.location.hostname === 'localhost' || 
    window.location.hostname === '127.0.0.1' || 
    window.location.hostname === ''
) ? 'http://localhost:8000' : 'https://mediqueue-project.onrender.com';

