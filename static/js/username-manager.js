class UsernameManager {
    constructor() {
        this.init();
    }

    init() {
        this.loadUsernames();
        this.setupEventListeners();
    }

    setupEventListeners() {
        const form = document.getElementById('add-username-form');
        form.addEventListener('submit', (e) => this.handleAddUsername(e));
    }

    async loadUsernames() {
        try {
            const response = await fetch('/api/usernames');
            const data = await response.json();
            if (data.success) {
                this.renderUsernames(data.usernames);
            }
        } catch (error) {
            console.error('Error loading usernames:', error);
        }
    }

    renderUsernames(usernames) {
        const list = document.getElementById('username-list');
        list.innerHTML = usernames.map(username => `
            <div class="username-item">
                <span>@${username}</span>
                <button class="delete-username"
                        onclick="usernameManager.deleteUsername('${username}')">
                    Delete
                </button>
            </div>
        `).join('');
    }

    async handleAddUsername(e) {
        e.preventDefault();
        const input = document.getElementById('new-username');
        const username = input.value.trim();

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
                alert('Error adding username');
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
                    alert('Error deleting username');
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
