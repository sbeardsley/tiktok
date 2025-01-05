let initialized = false;

function initializeApp() {
    // Prevent double initialization
    if (initialized) {
        console.log('App already initialized, skipping...');
        return;
    }

    window.currentPage = -1;  // Start at -1 so first loadMoreVideos() gets page 0
    window.filteredVideos = [];
    window.selectedFilters = new Set();
    window.hasMoreVideos = true;
    window.isLoading = false;

    console.log('Initializing app...');
    loadMoreVideos();  // Load first page
    setupInfiniteScroll();
    setupFilterHandlers();

    initialized = true;
}

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
        return;
    }

    const nextPage = window.currentPage + 1;
    window.isLoading = true;

    // Build query parameters including filters
    const params = new URLSearchParams({
        page: nextPage,
        per_page: window.videosPerPage
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

    // Fetch the next page of videos with filters
    fetch(`/api/videos?${params.toString()}`)
        .then(response => response.json())
        .then(data => {
            if (data.videos && data.videos.length > 0) {
                window.currentPage = nextPage;
                // Append only the new videos
                window.filteredVideos = window.filteredVideos.concat(data.videos);
                // Display only the new page of videos
                displayVideos(data.videos);
                window.hasMoreVideos = data.has_more;
            } else {
                window.hasMoreVideos = false;
            }
        })
        .catch(error => {
            console.error('Error loading more videos:', error);
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

function addFilter(filter) {
    window.selectedFilters.add(filter);
    updateSelectedFiltersDisplay();
    resetAndFilterVideos();
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

    card.innerHTML = `
        <div class="video-content">
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
        </div>
    `;

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
