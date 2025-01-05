class QueueDashboard {
    constructor() {
        this.updateInterval = 5000; // Update every 5 seconds
        this.init();
    }

    init() {
        this.updateStats();
        setInterval(() => this.updateStats(), this.updateInterval);
    }

    async updateStats() {
        try {
            const response = await fetch('/api/queue-stats');
            const data = await response.json();

            if (data.success) {
                this.updateQueueCards(data.stats);
                this.updateActivityList(data.recent_activity);
            }
        } catch (error) {
            console.error('Error updating queue stats:', error);
        }
    }

    updateQueueCards(stats) {
        // Update manifest queue stats
        document.getElementById('manifest-waiting').textContent =
            stats.manifest.waiting;
        document.getElementById('manifest-processing').textContent =
            stats.manifest.processing;
        document.getElementById('manifest-failed').textContent =
            stats.manifest.failed;

        // Update download queue stats
        document.getElementById('download-waiting').textContent =
            stats.download.waiting;
        document.getElementById('download-processing').textContent =
            stats.download.processing;
        document.getElementById('download-failed').textContent =
            stats.download.failed;
    }

    updateActivityList(activities) {
        const list = document.getElementById('activity-list');
        list.innerHTML = activities.map(activity => `
            <div class="activity-item">
                <div class="activity-info">
                    <strong>${activity.username}</strong>
                    <span>${activity.action}</span>
                </div>
                <span class="activity-status status-${activity.status.toLowerCase()}">
                    ${activity.status}
                </span>
                <span class="activity-time">
                    ${this.formatTime(activity.timestamp)}
                </span>
            </div>
        `).join('');
    }

    formatTime(timestamp) {
        const date = new Date(timestamp * 1000);
        return date.toLocaleString();
    }
}

// Initialize when document is ready
document.addEventListener('DOMContentLoaded', () => {
    window.queueDashboard = new QueueDashboard();
});
