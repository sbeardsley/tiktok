class UsernameManager {
    constructor() {
        this.init();
    }

    init() {
        this.loadUsernames();
        this.setupEventListeners();
    }

    setupEventListeners() {
        document.getElementById('add-username').addEventListener('click', (e) => this.handleAddUsername(e));
    }

    async loadUsernames() {
        try {
            const response = await fetch('/api/usernames');
            const data = await response.json();
            if (data.success) {
                this.renderUsernames(data.usernames);
            } else {
                console.error('Error loading usernames:', data.error);
            }
        } catch (error) {
            console.error('Error loading usernames:', error);
        }
    }

    renderUsernames(usernames) {
        const list = document.getElementById('username-list');
        if (!list) return;

        list.innerHTML = usernames.map(username => `
            <div class="username-item">
                <span class="username">@${username}</span>
                <button class="delete-btn" onclick="usernameManager.deleteUsername('${username}')">
                    <svg width="16" height="16" viewBox="0 0 16 16">
                        <path d="M5.5 5.5A.5.5 0 0 1 6 6v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm2.5 0a.5.5 0 0 1 .5.5v6a.5.5 0 0 1-1 0V6a.5.5 0 0 1 .5-.5zm3 .5a.5.5 0 0 0-1 0v6a.5.5 0 0 0 1 0V6z"/>
                        <path fill-rule="evenodd" d="M14.5 3a1 1 0 0 1-1 1H13v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V4h-.5a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1H6a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1h3.5a1 1 0 0 1 1 1v1zM4.118 4 4 4.059V13a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4.059L11.882 4H4.118zM2.5 3V2h11v1h-11z"/>
                    </svg>
                </button>
            </div>
        `).join('');
    }

    async handleAddUsername(e) {
        e.preventDefault();
        const input = document.getElementById('username-input');
        const username = input.value.trim();

        if (!username) {
            alert('Please enter at least one username');
            return;
        }

        try {
            const response = await fetch('/api/usernames', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username})
            });

            const data = await response.json();
            if (data.success) {
                input.value = '';
                this.loadUsernames();
            } else {
                alert('Error adding username: ' + (data.error || 'Unknown error'));
            }
        } catch (error) {
            console.error('Error adding username:', error);
            alert('Error adding username');
        }
    }

    async deleteUsername(username) {
        if (confirm(`Are you sure you want to delete @${username}?`)) {
            try {
                const response = await fetch('/api/usernames', {
                    method: 'DELETE',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username})
                });

                const data = await response.json();
                if (data.success) {
                    this.loadUsernames();
                } else {
                    alert('Error deleting username: ' + (data.error || 'Unknown error'));
                }
            } catch (error) {
                console.error('Error deleting username:', error);
                alert('Error deleting username');
            }
        }
    }
}

// Initialize when document is ready
document.addEventListener('DOMContentLoaded', () => {
    window.usernameManager = new UsernameManager();
});
