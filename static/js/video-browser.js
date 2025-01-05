// Use a more specific global flag and initialization tracking
window._videoAppInitialized = window._videoAppInitialized || false;
window._videoAppInitializing = window._videoAppInitializing || false;

// Define initializeApp first
function initializeApp() {
    if (window._videoAppInitialized || window._videoAppInitializing) {
        console.log('Initialization already in progress or completed');
        return;
    }

    window._videoAppInitializing = true;
    console.log('Starting initialization...');

    // Initialize global variables
    window.currentPage = -1;
    window.filteredVideos = [];
    window.selectedFilters = new Set();
    window.hasMoreVideos = true;
    window.isLoading = false;
    window.selectedVideos = new Set();
    window.selectionMode = false;
    window.videosPerPage = 20;

    // Hide batch actions initially
    const batchActions = document.querySelector('.batch-actions');
    if (batchActions) {
        batchActions.style.display = 'none';
    }

    console.log('Setting up components...');
    setupInfiniteScroll();
    setupFilterHandlers();
    setupSelectionMode();

    // Load first page
    console.log('Loading initial videos...');
    loadMoreVideos();

    window._videoAppInitialized = true;
    window._videoAppInitializing = false;
}

// Single initialization point with defensive check
document.addEventListener('DOMContentLoaded', () => {
    if (window._videoAppInitialized || window._videoAppInitializing) {
        console.log('App already initialized or initializing, skipping...');
        return;
    }

    console.log('Starting fresh initialization...');
    initializeApp();
});

function setupFilterHandlers() {
    const filterInput = document.getElementById('filter-input');
    const filterContainer = filterInput.parentElement;
    const orToggle = document.getElementById('or-filter-toggle');
    const notToggle = document.getElementById('not-filter-toggle');

    // Ensure the container has relative positioning
    filterContainer.style.position = 'relative';

    filterInput.addEventListener('input', handleFilterInput);
    filterInput.addEventListener('keydown', handleFilterKeydown);

    orToggle.addEventListener('change', function() {
        window.useOrFilter = this.checked;
        resetAndFilterVideos();
    });

    notToggle.addEventListener('change', function() {
        window.useNotFilter = this.checked;
        resetAndFilterVideos();
    });
}

function resetAndFilterVideos() {
    window.currentPage = -1;
    window.filteredVideos = [];
    window.hasMoreVideos = true;

    const container = document.getElementById('videos-grid');
    container.innerHTML = '';

    loadMoreVideos();
}

function displayVideos(newVideos) {
    const container = document.getElementById('videos-grid');

    // Only clear container on first page
    if (window.currentPage === 0) {
        container.innerHTML = '';
    }

    // Append only the new videos
    newVideos.forEach(video => {
        container.appendChild(createVideoCard(video));
    });
}

function setupInfiniteScroll() {
    window.addEventListener('scroll', () => {
        if (window.isLoading) {
            //console.log('Still loading, skipping scroll event');
            return;
        }

        const scrollPosition = window.scrollY + window.innerHeight;
        const pageHeight = document.documentElement.scrollHeight;
        const distanceFromBottom = pageHeight - scrollPosition;

        // console.log('Scroll check - Distance from bottom:', distanceFromBottom);

        if (distanceFromBottom < 500) {
            loadMoreVideos();
        }
    });
}

function loadMoreVideos() {
    if (window.isLoading || !window.hasMoreVideos) {
        console.log('Skipping load: loading=', window.isLoading, 'hasMore=', window.hasMoreVideos);
        return;
    }

    const nextPage = window.currentPage + 1;  // Will start at page 0
    window.isLoading = true;
    console.log('Loading page:', nextPage);

    // Build query parameters including filters
    const params = new URLSearchParams({
        page: nextPage,
        per_page: window.videosPerPage || 20
    });

    // Add filters and filter type if any are selected
    if (window.selectedFilters && window.selectedFilters.size > 0) {
        Array.from(window.selectedFilters).forEach(filter => {
            params.append('filters[]', filter);
        });

        // Add filter type (and/or/not)
        if (window.useNotFilter) {
            params.append('filter_type', 'not');
        } else if (window.useOrFilter) {
            params.append('filter_type', 'or');
        } else {
            params.append('filter_type', 'and');
        }
    }

    const url = `/api/videos?${params.toString()}`;
    console.log('Fetching videos with URL:', url); // Debug log

    // Fetch the next page of videos with filters
    fetch(url)
        .then(response => response.json())
        .then(data => {
            console.log('Received data:', data);
            if (data.videos && data.videos.length > 0) {
                window.currentPage = nextPage;  // Update current page after successful load
                window.filteredVideos = window.filteredVideos.concat(data.videos);
                displayVideos(data.videos);
                window.hasMoreVideos = data.has_more;
                console.log('Loaded page', nextPage, 'with', data.videos.length, 'videos');
            } else {
                window.hasMoreVideos = false;
                console.log('No more videos available');
            }
        })
        .catch(error => {
            console.error('Error loading videos:', error);
        })
        .finally(() => {
            window.isLoading = false;
        });
}

function displayNewVideos(videos) {
    const container = document.getElementById('videos-grid');

    videos.forEach(video => {
        container.appendChild(createVideoCard(video));
    });
}

function handleFilterInput(event) {
    const input = event.target.value.toLowerCase();
    const suggestions = document.getElementById('tag-suggestions');

    if (input.length === 0) {
        suggestions.style.display = 'none';
        return;
    }

    // Add loading indicator
    suggestions.innerHTML = '<div class="loading-spinner">Loading...</div>';
    suggestions.style.display = 'block';

    // Debounce the API call
    if (window.tagSearchTimeout) {
        clearTimeout(window.tagSearchTimeout);
    }

    window.tagSearchTimeout = setTimeout(() => {
        fetch(`/api/tags/search?q=${encodeURIComponent(input)}`)
            .then(response => response.json())
            .then(data => {
                if (data.tags && data.tags.length > 0) {
                    suggestions.innerHTML = data.tags
                        .map(tag => `<div class="tag-suggestion" onclick="addFilterAndHideSuggestions('${tag}')">${tag}</div>`)
                        .join('');
                } else {
                    suggestions.innerHTML = '<div class="no-results">No matching tags found</div>';
                }
                suggestions.style.display = 'block';
            })
            .catch(error => {
                console.error('Error searching tags:', error);
                suggestions.innerHTML = '<div class="error">Error loading tags</div>';
            });
    }, 300);
}

function handleFilterKeydown(event) {
    const filterInput = document.getElementById('filter-input');
    const suggestions = document.getElementById('tag-suggestions');

    if (event.key === 'Enter') {
        event.preventDefault();

        // If there's input, add it as a filter
        if (filterInput.value.trim()) {
            addFilter(filterInput.value.trim());
            filterInput.value = '';

            // Hide suggestions
            suggestions.style.display = 'none';
        }
    }
}

function addFilter(tag) {
    if (!tag) return;

    console.log('Adding filter:', tag); // Debug log

    // Add the tag directly to the Set
    window.selectedFilters.add(tag);

    // Update UI and reload videos
    updateFilterUI();
    resetAndFilterVideos();
}

function updateFilterUI() {
    const container = document.getElementById('selected-filters');
    container.innerHTML = '';

    window.selectedFilters.forEach(tag => {
        const filterTag = document.createElement('div');
        filterTag.className = 'filter-tag';
        filterTag.innerHTML = `
            ${tag}
            <span class="remove-tag" onclick="removeFilter('${tag}')">×</span>
        `;
        container.appendChild(filterTag);
    });
}

function removeFilter(filter) {
    window.selectedFilters.delete(filter);
    updateSelectedFiltersDisplay();
    resetAndFilterVideos();
}

function updateSelectedFiltersDisplay() {
    const container = document.getElementById('selected-filters');
    container.innerHTML = Array.from(window.selectedFilters)
        .map(filter => `
            <span class="filter-tag ${filter.startsWith('@') ? 'username-tag' : ''}">
                ${filter}
                <span class="remove-tag" onclick="removeFilter('${filter}')">&times;</span>
            </span>
        `)
        .join('');
}

function createVideoCard(video) {
    const card = document.createElement('div');
    card.className = 'video-card';
    card.dataset.videoId = video.video_id;

    // Add selection indicator
    const selectionIndicator = document.createElement('div');
    selectionIndicator.className = 'selection-indicator';
    selectionIndicator.textContent = '✓';

    // Parse author string
    let displayName = video.username; // Default to username from metadata
    let relativeTime = video.author.split('·')[1];
    if (video.author) {
        // Try to extract the full name from the author string
        const authorParts = video.author.split('·')[0]; // Get part before the dot
        if (authorParts) {
            // Check if authorParts contains the username
            if (authorParts.includes(video.username)) {
                // Remove the username portion to get the display name
                displayName = authorParts.replace(video.username, '').trim();
            } else {
                // If no username found, use the whole authorParts
                displayName = authorParts.trim();
            }

            // If we ended up with an empty display name, fall back to username
            if (!displayName) {
                displayName = video.username;
            }
        }
    }

    const videoContent = document.createElement('div');
    videoContent.className = 'video-content';
    videoContent.innerHTML = `
        <div class="video-thumbnail-container">
            ${video.has_thumbnail ?
                `<img src="/thumbnail/${video.thumbnail_path}"
                      class="video-thumbnail"
                      onclick="playVideo(this, '${video.video_path}')"
                      alt="Video thumbnail">` :
                `<div class="thumbnail-loading">
                    <div class="spinner"></div>
                </div>`
            }
            <button class="delete-button" onclick="showDeleteConfirmation(event)">×</button>
        </div>
        <div class="video-info">
            <div class="author-container">
                <h3 class="author">${displayName}</h3>
                <span class="time">${relativeTime}</span>
            </div>
            ${video.description ?
                `<div class="video-description">${video.description.slice(0, 100)}...</div>` :
                ''
            }
            <div class="video-tags">
                ${(video.tags || [])
                    .map(tag => `<span class="video-tag" onclick="addFilter('${tag}')">${tag}</span>`)
                    .join('')
                }
                ${video.username ?
                    `<span class="video-tag username-tag" onclick="addFilter('@${video.username}')">@${video.username}</span>` :
                    ''
                }
            </div>
        </div>
    `;

    // Add click handler for selection
    card.addEventListener('click', handleVideoCardClick);

    // Append elements in the correct order
    card.appendChild(selectionIndicator);
    card.appendChild(videoContent);

    return card;
}

function playVideo(thumbnailElement, videoPath) {
    // Create video element
    const video = document.createElement('video');
    video.controls = true;
    video.style.width = '100%';
    video.style.height = '100%';
    video.style.position = 'absolute';
    video.style.top = '0';
    video.style.left = '0';
    video.style.objectFit = 'cover';

    // Create source element
    const source = document.createElement('source');
    source.src = `/video/${videoPath}`;
    source.type = 'video/mp4';

    // Add source to video
    video.appendChild(source);

    // Replace thumbnail with video while maintaining container
    const container = thumbnailElement.parentElement;
    container.replaceChild(video, thumbnailElement);

    // Play the video
    video.play().catch(e => console.log('Error playing video:', e));
}

// Initialize with reasonable page size
window.videosPerPage = 20;  // Show 20 videos per page

// Add some CSS for the loading state
const style = document.createElement('style');
style.textContent = `
    .loading-spinner {
        padding: 10px;
        text-align: center;
        color: #666;
    }
    .no-results {
        padding: 10px;
        text-align: center;
        color: #666;
    }
    .error {
        padding: 10px;
        text-align: center;
        color: #f44336;
    }
    .filter-input-container {
        position: relative;
        display: inline-block;
    }
    #filter-input {
        width: 100%;
    }
    #tag-suggestions {
        position: absolute;
        top: calc(100% / 4);  /* Position right below input with small gap */
        left: 0;
        width: 100%;
        max-height: 300px;
        overflow-y: auto;
        background: white;
        border: 1px solid #ddd;
        border-radius: 4px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        z-index: 1001;
    }
    .tag-suggestion {
        padding: 8px 12px;
        cursor: pointer;
    }
    .tag-suggestion:hover {
        background-color: #f5f5f5;
    }
`;
document.head.appendChild(style);

function addFilterAndHideSuggestions(filter) {
    // Add the filter
    addFilter(filter);

    // Clear the input
    const filterInput = document.getElementById('filter-input');
    filterInput.value = '';

    // Hide suggestions
    const suggestions = document.getElementById('tag-suggestions');
    suggestions.style.display = 'none';
}

function showDeleteConfirmation(event) {
    // Prevent the click from propagating to the video
    event.stopPropagation();

    // Find the video card
    const videoCard = event.target.closest('.video-card');
    const videoContent = videoCard.querySelector('.video-content');

    // Check if confirmation is already showing
    if (videoCard.querySelector('.delete-confirmation')) {
        return;
    }

    // Create and insert confirmation overlay
    const confirmation = document.createElement('div');
    confirmation.className = 'delete-confirmation';
    confirmation.innerHTML = `
        <div class="delete-message">Delete this video?</div>
        <div class="delete-buttons">
            <button class="delete-confirm">Delete</button>
            <button class="delete-cancel">Cancel</button>
        </div>
    `;

    // Add event listeners
    confirmation.querySelector('.delete-confirm').addEventListener('click', (e) => {
        e.stopPropagation();
        deleteVideo(videoCard.dataset.videoId, videoCard);
    });

    confirmation.querySelector('.delete-cancel').addEventListener('click', (e) => {
        e.stopPropagation();
        confirmation.remove();
    });

    videoContent.appendChild(confirmation);
}

// Add CSS for the delete confirmation
const deleteStyle = document.createElement('style');
deleteStyle.textContent = `
    .delete-confirmation {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.8);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 15px;
        z-index: 1000;
    }

    .delete-message {
        color: white;
        font-size: 1.2em;
        text-align: center;
    }

    .delete-buttons {
        display: flex;
        gap: 10px;
    }

    .delete-buttons button {
        padding: 8px 16px;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        font-weight: bold;
    }

    .delete-confirm {
        background: #dc3545;
        color: white;
    }

    .delete-confirm:hover {
        background: #c82333;
    }

    .delete-cancel {
        background: #6c757d;
        color: white;
    }

    .delete-cancel:hover {
        background: #5a6268;
    }

    .video-content {
        position: relative;
    }
`;
document.head.appendChild(deleteStyle);

function deleteVideo(videoId, videoCard) {
    // Use the bulk delete endpoint with a single video ID
    fetch('/api/videos/bulk-delete', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ video_ids: [videoId] })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Remove the video card from the UI with a fade effect
            videoCard.style.transition = 'opacity 0.3s ease';
            videoCard.style.opacity = '0';
            setTimeout(() => {
                videoCard.remove();
            }, 300);
        } else {
            alert('Error deleting video: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error deleting video. Please try again.');
    });
}

// Add CSS for video card selection
const selectionStyle = document.createElement('style');
selectionStyle.textContent = `
    .video-card {
        position: relative;
        cursor: pointer;
        user-select: none;
    }

    .video-card.selected {
        outline: 3px solid #007bff;
    }

    .selection-indicator {
        position: absolute;
        top: 10px;
        left: 10px;
        width: 24px;
        height: 24px;
        border-radius: 50%;
        background: #007bff;
        color: white;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: bold;
        z-index: 10;
        opacity: 0;
        transition: opacity 0.2s ease;
    }

    .video-card.selected .selection-indicator {
        opacity: 1;
    }

    .video-card:hover .selection-indicator {
        opacity: 0.5;
    }

    .video-card.selected:hover .selection-indicator {
        opacity: 1;
    }

    .selection-mode-button {
        position: fixed;
        bottom: 20px;
        right: 20px;
        padding: 12px 24px;
        background: #007bff;
        color: white;
        border: none;
        border-radius: 25px;
        cursor: pointer;
        font-weight: bold;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        z-index: 1000;
        transition: background-color 0.2s;
    }

    .selection-mode-button:hover {
        background: #0056b3;
    }

    .selection-mode-button.active {
        background: #dc3545;
    }

    /* Hide selection indicators when not in selection mode */
    :not(.selection-mode) .selection-indicator {
        display: none;
    }
`;
document.head.appendChild(selectionStyle);

function setupSelectionMode() {
    const button = document.querySelector('.selection-mode-button');
    const batchActions = document.querySelector('.batch-actions');
    const batchTagInput = document.getElementById('batch-tag-input');
    const deleteButton = document.getElementById('batch-delete-button');

    // Create and add the apply tag button
    const batchTagContainer = document.querySelector('.batch-tag-input-container');
    if (batchTagContainer && !document.getElementById('apply-batch-tag-button')) {
        const applyTagButton = document.createElement('button');
        applyTagButton.id = 'apply-batch-tag-button';
        applyTagButton.textContent = 'Add Tag';
        applyTagButton.className = 'btn btn-primary';
        applyTagButton.style.marginLeft = '10px';
        applyTagButton.onclick = applyBatchTag;
        batchTagContainer.appendChild(applyTagButton);
    }

    console.log('Selection mode setup:', {
        buttonFound: !!button,
        batchActionsFound: !!batchActions,
        batchTagInputFound: !!batchTagInput,
        deleteButtonFound: !!deleteButton
    });

    // Skip setup if elements aren't found
    if (!button) {
        console.error('Selection mode button not found. Selector: .selection-mode-button');
        createSelectionModeButton();
        return;
    }

    // Hide batch actions initially
    if (batchActions) {
        batchActions.style.display = 'none';
    }

    button.addEventListener('click', () => {
        window.selectionMode = !window.selectionMode;

        // Toggle selection mode class on body
        document.body.classList.toggle('selection-mode', window.selectionMode);

        // Update button state
        button.classList.toggle('active');
        button.textContent = window.selectionMode ? 'Exit Selection' : 'Select Videos';

        // Show/hide batch actions
        if (batchActions) {
            batchActions.style.display = window.selectionMode ? 'flex' : 'none';
        }

        // Show/hide batch tag input
        if (batchTagInput) {
            batchTagInput.style.display = window.selectionMode ? 'block' : 'none';
        }

        // Show/hide delete button
        if (deleteButton) {
            deleteButton.style.display = window.selectionMode ? 'block' : 'none';
        }

        // Clear selections when exiting selection mode
        if (!window.selectionMode) {
            window.selectedVideos.clear();
            document.querySelectorAll('.video-card').forEach(card => {
                card.classList.remove('selected');
            });
            updateSelectionUI();
        }
    });
}

function createSelectionModeButton() {
    console.log('Creating selection mode button');
    const button = document.createElement('button');
    button.className = 'selection-mode-button';
    button.textContent = 'Select Videos';
    button.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        padding: 12px 24px;
        background: #007bff;
        color: white;
        border: none;
        border-radius: 25px;
        cursor: pointer;
        font-weight: bold;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        z-index: 1000;
    `;

    document.body.appendChild(button);

    // Re-run setup with the new button
    setupSelectionMode();
}

function clearSelections() {
    window.selectedVideos.clear();
    document.querySelectorAll('.video-card').forEach(card => {
        card.classList.remove('selected');
    });
    updateSelectionUI();
}

function handleVideoCardClick(event) {
    // Only handle selection if in selection mode
    if (!window.selectionMode) {
        return;
    }

    // Ignore clicks on specific elements
    if (event.target.closest('.delete-button') ||
        event.target.closest('.delete-confirmation') ||
        event.target.closest('.video-tag')) {
        return;
    }

    const card = event.currentTarget;
    const videoId = card.dataset.videoId;

    console.log('Click handled, current selection size:', window.selectedVideos.size); // Debug

    // Handle selection with shift key for range selection
    if (event.shiftKey && window.lastSelectedVideo) {
        const cards = Array.from(document.querySelectorAll('.video-card'));
        const lastIndex = cards.findIndex(c => c.dataset.videoId === window.lastSelectedVideo);
        const currentIndex = cards.findIndex(c => c.dataset.videoId === videoId);

        const start = Math.min(lastIndex, currentIndex);
        const end = Math.max(lastIndex, currentIndex);

        for (let i = start; i <= end; i++) {
            const card = cards[i];
            card.classList.add('selected');
            window.selectedVideos.add(card.dataset.videoId);
        }
    }
    // Handle selection with ctrl/cmd key for multiple selection
    else if (event.ctrlKey || event.metaKey) {
        card.classList.toggle('selected');
        if (card.classList.contains('selected')) {
            window.selectedVideos.add(videoId);
            window.lastSelectedVideo = videoId;
        } else {
            window.selectedVideos.delete(videoId);
        }
    }
    // Normal click for single selection
    else {
        // Deselect all other cards
        document.querySelectorAll('.video-card.selected').forEach(c => {
            c.classList.remove('selected');
        });
        window.selectedVideos.clear();

        // Select this card
        card.classList.add('selected');
        window.selectedVideos.add(videoId);
        window.lastSelectedVideo = videoId;
    }

    console.log('After selection, size:', window.selectedVideos.size); // Debug

    // Update selection count or trigger other actions
    updateSelectionUI();
}

function updateSelectionUI() {
    const count = window.selectedVideos.size;
    console.log('Updating UI with count:', count);

    // Update the count display
    const countSpan = document.getElementById('selected-count');
    if (countSpan) {
        countSpan.textContent = count;
    }

    // Show/hide batch actions based on selection
    const batchActions = document.querySelector('.batch-actions');
    if (batchActions) {
        batchActions.style.display = (window.selectionMode && count > 0) ? 'flex' : 'none';
    }

    // Update delete button visibility
    const deleteButton = document.getElementById('batch-delete-button');
    if (deleteButton) {
        deleteButton.style.display = (window.selectionMode && count > 0) ? 'block' : 'none';
    }
}

// Add styles for the delete selected button
const deleteSelectedStyle = document.createElement('style');
deleteSelectedStyle.textContent = `
    .delete-selected-button {
        position: fixed;
        bottom: 20px;
        right: 200px; /* Position to the left of selection mode button */
        padding: 12px 24px;
        background: #dc3545;
        color: white;
        border: none;
        border-radius: 25px;
        cursor: pointer;
        font-weight: bold;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
        z-index: 1000;
        transition: all 0.2s ease;
    }

    .delete-selected-button:hover {
        background: #c82333;
    }
`;
document.head.appendChild(deleteSelectedStyle);

function deleteSelectedVideos() {
    if (window.selectedVideos.size === 0) return;

    if (confirm(`Are you sure you want to delete ${window.selectedVideos.size} videos?`)) {
        // Convert Set to Array for the fetch request
        const videoIds = Array.from(window.selectedVideos);

        fetch('/api/videos/bulk-delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ video_ids: videoIds })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Remove deleted videos from the UI
                videoIds.forEach(videoId => {
                    const card = document.querySelector(`.video-card[data-video-id="${videoId}"]`);
                    if (card) {
                        card.style.transition = 'opacity 0.3s ease';
                        card.style.opacity = '0';
                        setTimeout(() => card.remove(), 300);
                    }
                });

                // Clear selections
                window.selectedVideos.clear();
                updateSelectionUI();
            } else {
                alert('Error deleting videos: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Error deleting videos. Please try again.');
        });
    }
}

function confirmBatchDelete() {
    const selectedCount = window.selectedVideos.size;
    if (selectedCount === 0) {
        alert('No videos selected');
        return;
    }

    if (confirm(`Are you sure you want to delete ${selectedCount} videos?`)) {
        const videoIds = Array.from(window.selectedVideos);

        // Call the bulk delete endpoint
        fetch('/api/videos/bulk-delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ video_ids: videoIds })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Remove all deleted videos from the UI
                videoIds.forEach(videoId => {
                    const videoCard = document.querySelector(`.video-card[data-video-id="${videoId}"]`);
                    if (videoCard) {
                        videoCard.style.transition = 'opacity 0.3s ease';
                        videoCard.style.opacity = '0';
                        setTimeout(() => {
                            videoCard.remove();
                        }, 300);
                    }
                });

                // Clear selections
                window.selectedVideos.clear();
                updateSelectionUI();

                // Show success message
                alert(data.summary);
            } else {
                alert('Error deleting videos: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Error deleting videos. Please try again.');
        });
    }
}

function cancelBatchSelection() {
    // Clear selections
    window.selectedVideos.clear();

    // Update UI
    document.querySelectorAll('.video-card').forEach(card => {
        card.classList.remove('selected');
    });

    // Update selection count
    updateSelectionUI();

    // Exit selection mode
    window.selectionMode = false;
    document.body.classList.remove('selection-mode');

    // Update selection mode button
    const button = document.querySelector('.selection-mode-button');
    if (button) {
        button.textContent = 'Select Videos';
        button.classList.remove('active');
    }

    // Hide batch actions but don't remove them
    const batchActions = document.querySelector('.batch-actions');
    if (batchActions) {
        batchActions.style.display = 'none';
    }
}

function selectVisibleVideos() {
    // Get all visible video cards
    const visibleCards = document.querySelectorAll('.video-card');

    console.log('Selecting visible videos:', visibleCards.length);

    // Add each visible video to the selection
    visibleCards.forEach(card => {
        const videoId = card.dataset.videoId;
        if (videoId) {
            window.selectedVideos.add(videoId);
            card.classList.add('selected');
        }
    });

    // Update the selection UI
    updateSelectionUI();
}

function applyBatchTag() {
    const tagInput = document.getElementById('batch-tag-input');
    if (!tagInput || !tagInput.value.trim()) {
        alert('Please enter a tag');
        return;
    }

    const tag = tagInput.value.trim();
    const videoIds = Array.from(window.selectedVideos);

    if (videoIds.length === 0) {
        alert('No videos selected');
        return;
    }

    // Call the API to add tags
    fetch('/api/videos/bulk-tag', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            video_ids: videoIds,
            tag: tag
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Clear the input
            tagInput.value = '';

            // Show success message
            alert(`Tag "${tag}" added to ${videoIds.length} videos`);

            // Optionally refresh the video cards to show new tags
            videoIds.forEach(videoId => {
                const card = document.querySelector(`.video-card[data-video-id="${videoId}"]`);
                if (card) {
                    // Add the new tag to the video's tag container
                    const tagsContainer = card.querySelector('.video-tags');
                    if (tagsContainer) {
                        const tagSpan = document.createElement('span');
                        tagSpan.className = 'video-tag';
                        tagSpan.textContent = tag;
                        tagSpan.onclick = () => addFilter(tag);
                        tagsContainer.appendChild(tagSpan);
                    }
                }
            });
        } else {
            alert('Error adding tags: ' + (data.error || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('Error adding tags. Please try again.');
    });
}
