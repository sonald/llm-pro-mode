/**
 * LLM Pro Mode Web UI Application
 * Handles WebSocket communication, UI updates, and task monitoring
 */

class LLMProWebApp {
    constructor() {
        this.ws = null;
        this.currentTasks = new Map();
        this.messageHistory = [];
        this.isConnected = false;
        this.activeModalTaskId = null;
        this.isProcessing = false;
        this.stats = {
            totalTokens: 0,
            avgTime: 0,
            successRate: 100,
            totalTasks: 0
        };

        this.profileData = null;
        this.activeProfileName = null;
        this.defaultProfileName = null;

        this.initializeMarked();
        this.initializeElements();
        this.bindEvents();
        this.fetchProfiles();
        this.connectWebSocket();
    }

    initializeMarked() {
        // Configure marked.js with security and syntax highlighting
        console.log('Initializing marked.js...');
        console.log('marked available:', typeof marked !== 'undefined');
        console.log('Prism available:', typeof Prism !== 'undefined');

        if (typeof marked !== 'undefined') {
            console.log('Configuring marked.js options');
            marked.setOptions({
                highlight: function(code, lang) {
                    console.log('Highlighting code for language:', lang);
                    if (typeof Prism !== 'undefined' && lang && Prism.languages[lang]) {
                        return Prism.highlight(code, Prism.languages[lang], lang);
                    }
                    return code;
                },
                breaks: true,
                gfm: true,
                sanitize: false, // We'll use DOMPurify for sanitization if needed
                smartLists: true,
                smartypants: true
            });
            console.log('marked.js configured successfully');
        } else {
            console.warn('marked.js is not available!');
        }
    }

    initializeElements() {
        // Chat elements
        this.chatContainer = document.getElementById('chat-container');
        this.messageInput = document.getElementById('message-input');
        this.chatForm = document.getElementById('chat-form');
        this.sendBtn = document.getElementById('send-btn');
        this.stopBtn = document.getElementById('stop-btn');
        this.nRunsSelect = document.getElementById('n-runs');
        this.enableTraceCheckbox = document.getElementById('enable-trace');

        // Monitor elements
        this.progressContainer = document.getElementById('progress-container');
        this.monitorStatus = document.getElementById('monitor-status');

        // Statistics elements
        this.totalTokensEl = document.getElementById('total-tokens');
        this.avgTimeEl = document.getElementById('avg-time');
        this.successRateEl = document.getElementById('success-rate');
        this.totalTasksEl = document.getElementById('total-tasks');

        // Connection status
        this.connectionStatus = document.getElementById('connection-status');
        this.statusIndicator = document.getElementById('status-indicator');
        this.statusText = document.getElementById('status-text');

        // Modal elements
        this.taskModal = document.getElementById('task-modal-overlay');
        this.taskModalTitle = document.getElementById('modal-title');
        this.modalClose = document.getElementById('modal-close');
        this.tabBtns = document.querySelectorAll('.tab-btn');
        this.thinkingContent = document.getElementById('thinking-content');
        this.contentContent = document.getElementById('content-content');
        this.metadataContent = document.getElementById('metadata-content');

        // Settings modal
        this.settingsModal = document.getElementById('settings-modal-overlay');
        this.settingsBtn = document.getElementById('settings-btn');
        this.settingsClose = document.getElementById('settings-close');
        this.clearBtn = document.getElementById('clear-btn');

        // Profile controls
        this.activeProfileLabel = document.getElementById('active-profile');
        this.profileSelect = document.getElementById('profile-select');
        this.applyProfileBtn = document.getElementById('apply-profile');
        this.setDefaultProfileCheckbox = document.getElementById('set-default-profile');

        // Settings inputs
        this.modelInput = document.getElementById('model-select');
        this.apiBaseInput = document.getElementById('api-base');
        this.apiKeyInput = document.getElementById('api-key');
    }

    bindEvents() {
        // Form submission
        this.chatForm.addEventListener('submit', (e) => this.handleSubmit(e));

        // Input handling
        this.messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.handleSubmit(e);
            }
        });

        // Modal events
        this.modalClose.addEventListener('click', () => this.closeTaskModal());
        this.taskModal.addEventListener('click', (e) => {
            if (e.target === this.taskModal) this.closeTaskModal();
        });

        // Tab switching
        this.tabBtns.forEach(btn => {
            btn.addEventListener('click', () => this.switchTab(btn.dataset.tab));
        });

        // Settings modal
        this.settingsBtn.addEventListener('click', () => this.openSettingsModal());
        this.settingsClose.addEventListener('click', () => this.closeSettingsModal());
        this.settingsModal.addEventListener('click', (e) => {
            if (e.target === this.settingsModal) this.closeSettingsModal();
        });

        // Clear chat
        this.clearBtn.addEventListener('click', () => this.clearChat());

        if (this.stopBtn) {
            this.stopBtn.addEventListener('click', () => this.handleStopRequest());
        }

        // Settings form
        document.getElementById('save-settings').addEventListener('click', () => this.saveSettings());
        document.getElementById('cancel-settings').addEventListener('click', () => this.closeSettingsModal());

        if (this.applyProfileBtn) {
            this.applyProfileBtn.addEventListener('click', () => this.handleProfileApply());
        }
        if (this.profileSelect) {
            this.profileSelect.addEventListener('change', () => this.handleProfileSelectionChange());
        }

        // ESC key handling
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeTaskModal();
                this.closeSettingsModal();
            }
        });
    }

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;

        try {
            this.ws = new WebSocket(wsUrl);
            this.updateConnectionStatus('connecting', 'Connecting...');

            this.ws.onopen = () => {
                this.isConnected = true;
                this.updateConnectionStatus('connected', 'Connected');
                this.updateMonitorStatus('Ready');
                console.log('WebSocket connected');
            };

            this.ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                this.handleWebSocketMessage(data);
            };

            this.ws.onclose = () => {
                this.isConnected = false;
                this.updateConnectionStatus('disconnected', 'Disconnected');
                this.updateMonitorStatus('Disconnected');
                this.setProcessingState(false);
                console.log('WebSocket disconnected');

                // Attempt to reconnect after 3 seconds
                setTimeout(() => this.connectWebSocket(), 3000);
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                this.updateConnectionStatus('disconnected', 'Connection Error');
                this.setProcessingState(false);
            };

        } catch (error) {
            console.error('Failed to connect:', error);
            this.updateConnectionStatus('disconnected', 'Failed to Connect');
        }
    }

    async fetchProfiles() {
        if (!this.profileSelect) return;

        try {
            const response = await fetch('/api/profiles');
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            this.populateProfileControls(data);
        } catch (error) {
            console.error('Failed to load profiles:', error);
        }
    }

    populateProfileControls(data) {
        this.profileData = data;
        this.activeProfileName = data.active_profile || null;
        this.defaultProfileName = data.default_profile || null;

        if (this.profileSelect) {
            this.profileSelect.innerHTML = '';

            data.profiles.forEach(profile => {
                const option = document.createElement('option');
                option.value = profile.name;
                option.textContent = profile.description ? `${profile.name} - ${profile.description}` : profile.name;
                option.dataset.model = profile.model_name || '';
                option.dataset.apiBase = profile.api_base || '';
                option.dataset.apiKeyPreview = profile.api_key_preview || '';
                this.profileSelect.appendChild(option);
            });

            if (data.active_profile) {
                this.profileSelect.value = data.active_profile;
            }

            const hasProfiles = data.profiles.length > 0;
            this.profileSelect.disabled = !hasProfiles;
            if (this.applyProfileBtn) {
                this.applyProfileBtn.disabled = !hasProfiles;
            }
            if (this.setDefaultProfileCheckbox) {
                this.setDefaultProfileCheckbox.disabled = !hasProfiles;
            }

            this.handleProfileSelectionChange();
        }

        this.updateProfileBadge(this.activeProfileName);
    }

    handleProfileSelectionChange() {
        if (!this.profileData || !this.profileSelect) {
            return;
        }

        const selected = this.profileSelect.value;
        const profile = this.profileData.profiles.find(item => item.name === selected);

        if (this.setDefaultProfileCheckbox) {
            this.setDefaultProfileCheckbox.checked = selected === this.defaultProfileName;
        }

        if (profile) {
            this.previewProfileDetails(profile);
        } else {
            this.previewProfileDetails({ model_name: '', api_base: '', api_key_preview: '' });
        }
    }

    updateProfileBadge(profileName) {
        if (!this.activeProfileLabel) return;
        const label = profileName ? `Profile: ${profileName}` : 'Profile: --';
        this.activeProfileLabel.textContent = label;
    }

    previewProfileDetails(profile) {
        if (this.modelInput) {
            this.modelInput.value = profile.model_name || '';
        }
        if (this.apiBaseInput) {
            this.apiBaseInput.value = profile.api_base || '';
        }
        if (this.apiKeyInput) {
            this.apiKeyInput.value = '';
            this.apiKeyInput.placeholder = profile.api_key_preview || 'sk-...';
        }
    }

    async handleProfileApply() {
        if (!this.profileSelect) return;

        const selectedProfile = this.profileSelect.value;
        if (!selectedProfile) return;

        const makeDefault = this.setDefaultProfileCheckbox ? this.setDefaultProfileCheckbox.checked : false;

        if (this.applyProfileBtn) {
            this.applyProfileBtn.disabled = true;
        }

        try {
            const response = await fetch('/api/profiles/select', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: selectedProfile, make_default: makeDefault })
            });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(errorText || `HTTP ${response.status}`);
            }

            const data = await response.json();
            this.populateProfileControls(data);
            this.updateMonitorStatus(`Profile set to ${data.active_profile || selectedProfile}`);
            setTimeout(() => this.updateMonitorStatus('Ready'), 2000);
        } catch (error) {
            console.error('Failed to apply profile:', error);
            this.updateMonitorStatus('Profile update failed');
            setTimeout(() => this.updateMonitorStatus('Ready'), 3000);
        } finally {
            if (this.applyProfileBtn) {
                this.applyProfileBtn.disabled = false;
            }
        }
    }

    handleWebSocketMessage(data) {
        switch (data.type) {
            case 'task_started':
                this.handleTaskStarted(data);
                break;
            case 'task_progress':
                this.handleTaskProgress(data);
                break;
            case 'task_completed':
                this.handleTaskCompleted(data);
                break;
            case 'synthesis_started':
                this.handleSynthesisStarted(data);
                break;
            case 'synthesis_completed':
                this.handleSynthesisCompleted(data);
                break;
            case 'task_cancelled':
                this.handleTaskCancelled(data);
                break;
            case 'error':
                this.handleError(data);
                break;
            case 'final_result':
                this.handleFinalResult(data);
                break;
            default:
                console.log('Unknown message type:', data.type);
        }
    }

    handleStopRequest() {
        if (!this.isConnected || !this.ws || !this.isProcessing) {
            return;
        }

        if (this.stopBtn) {
            this.stopBtn.disabled = true;
            const textEl = this.stopBtn.querySelector('.btn-text');
            if (textEl) textEl.textContent = 'Stopping...';
            const iconEl = this.stopBtn.querySelector('.btn-icon');
            if (iconEl) iconEl.textContent = '⏳';
        }

        if (this.sendBtn) {
            const textEl = this.sendBtn.querySelector('.btn-text');
            if (textEl) textEl.textContent = 'Cancelling...';
        }

        this.updateMonitorStatus('Cancelling...');
        this.ws.send(JSON.stringify({ type: 'cancel_request' }));
    }

    setProcessingState(isProcessing) {
        this.isProcessing = isProcessing;
        this.setSendButtonState(!isProcessing);

        if (this.stopBtn) {
            const textEl = this.stopBtn.querySelector('.btn-text');
            const iconEl = this.stopBtn.querySelector('.btn-icon');
            if (textEl) textEl.textContent = 'Stop';
            if (iconEl) iconEl.textContent = '⏹️';
            this.stopBtn.classList.toggle('visible', isProcessing);
            this.stopBtn.disabled = !isProcessing;
        }
    }

    handleSubmit(e) {
        e.preventDefault();
        const message = this.messageInput.value.trim();

        if (!message || !this.isConnected) return;

        const requestData = {
            prompt: message,
            n_runs: parseInt(this.nRunsSelect.value),
            enable_trace: this.enableTraceCheckbox.checked,
            trace_compact: true
        };

        // Add user message to chat
        this.addMessage('user', message);

        // Clear input and disable send button
        this.messageInput.value = '';
        this.setProcessingState(true);

        // Clear previous tasks
        this.clearProgressContainer();
        this.updateMonitorStatus('Processing...');

        // Send request via WebSocket
        this.ws.send(JSON.stringify({
            type: 'completion_request',
            data: requestData
        }));
    }

    handleTaskStarted(data) {
        const existingTask = this.currentTasks.get(data.task_id);

        if (existingTask) {
            existingTask.title = data.title || `Task ${data.task_id}`;
            existingTask.status = 'running';
            existingTask.progress = 0;
            existingTask.metadata = { ...existingTask.metadata, ...(data.metadata || {}) };
            existingTask.startTime = Date.now();
            delete existingTask.endTime;
            delete existingTask.duration;

            this.updateProgressCard(existingTask);
            this.refreshTaskModal(existingTask, { force: true });
        } else {
            const task = {
                id: data.task_id,
                title: data.title || `Task ${data.task_id}`,
                status: 'running',
                progress: 0,
                thinking: '',
                content: '',
                metadata: data.metadata || {},
                startTime: Date.now()
            };

            this.currentTasks.set(data.task_id, task);
            this.renderProgressCard(task);
        }

        this.updateTaskStats();
    }

    handleTaskProgress(data) {
        const task = this.currentTasks.get(data.task_id);
        if (!task) return;

        task.progress = data.progress || 0;

        if (data.thinking) {
            task.thinking += data.thinking;
        }

        if (data.content) {
            task.content += data.content;
        }

        this.updateProgressCard(task);
        this.refreshTaskModal(task);
    }

    handleTaskCompleted(data) {
        const task = this.currentTasks.get(data.task_id);
        if (!task) return;

        const finalStatus = data.status || (data.success ? 'completed' : 'failed');
        task.status = finalStatus;
        task.progress = 100;
        task.endTime = Date.now();
        task.duration = task.endTime - task.startTime;

        if (data.thinking) {
            task.thinking += data.thinking;
        }

        if (data.content) {
            task.content += data.content;
        }

        if (data.error) {
            task.error = data.error;
        }

        this.updateProgressCard(task);
        this.updateTaskStats();
        this.refreshTaskModal(task);
    }

    handleSynthesisStarted(data) {
        this.updateMonitorStatus('Synthesizing results...');

        // Reuse existing synthesis task created by task_started message when available
        let synthTask = this.currentTasks.get('synthesis');

        if (synthTask) {
            synthTask.status = 'running';
            synthTask.progress = synthTask.progress || 0;
            synthTask.metadata = { ...synthTask.metadata, type: 'synthesis' };
            synthTask.startTime = synthTask.startTime || Date.now();
            this.updateProgressCard(synthTask);
            this.refreshTaskModal(synthTask);
        } else {
            // Fallback: create task if the start notification was missed
            synthTask = {
                id: 'synthesis',
                title: 'Synthesis',
                status: 'running',
                progress: 0,
                thinking: '',
                content: '',
                metadata: { type: 'synthesis' },
                startTime: Date.now()
            };

            this.currentTasks.set('synthesis', synthTask);
            this.renderProgressCard(synthTask);
        }
    }

    handleSynthesisCompleted(data) {
        const task = this.currentTasks.get('synthesis');
        if (task) {
            const finalStatus = data.status || (data.success ? 'completed' : 'failed');
            task.status = finalStatus;
            task.progress = 100;
            task.endTime = Date.now();
            task.duration = task.endTime - task.startTime;

            // Accumulate thinking and content data
            if (data.thinking) {
                task.thinking = data.thinking;
            }

            if (data.content) {
                task.content = data.content;
            }

            if (data.error) {
                task.error = data.error;
            }

            this.updateProgressCard(task);
            this.refreshTaskModal(task);
        }

        const statusLabel = data.status === 'cancelled' ? 'Cancelled' : 'Completed';
        this.updateMonitorStatus(statusLabel);
    }

    handleFinalResult(data) {
        // Add assistant message to chat
        this.addMessage('assistant', data.content);

        this.setProcessingState(false);

        // Update statistics
        if (data.stats) {
            this.updateStatistics(data.stats);
        }
    }

    handleTaskCancelled(data) {
        const reason = data.reason || 'Cancelled by user';
        const hadActiveSession = this.isProcessing;

        this.setProcessingState(false);

        if (hadActiveSession) {
            const message = reason === 'Cancelled by user' ? '⏹️ Task cancelled.' : `⏹️ ${reason}`;
            this.addMessage('assistant', message);
            this.updateMonitorStatus('Cancelled');
        } else {
            this.updateMonitorStatus(reason);
        }

        setTimeout(() => {
            if (!this.isProcessing) {
                this.updateMonitorStatus('Ready');
            }
        }, 2000);
    }

    handleError(data) {
        console.error('Server error:', data.message);
        this.addMessage('assistant', `❌ Error: ${data.message}`);
        this.setProcessingState(false);
        this.updateMonitorStatus('Error');
    }

    addMessage(role, content) {
        const messageEl = document.createElement('div');
        messageEl.className = `message ${role}`;

        const avatar = document.createElement('div');
        avatar.className = 'message-avatar';
        avatar.textContent = role === 'user' ? '👤' : '🤖';

        const bubble = document.createElement('div');
        bubble.className = 'message-bubble';

        if (role === 'assistant') {
            // Render markdown for assistant messages
            bubble.innerHTML = this.renderMarkdown(content);
        } else {
            bubble.textContent = content;
        }

        messageEl.appendChild(avatar);
        messageEl.appendChild(bubble);

        // Remove welcome message if present
        const welcomeMsg = this.chatContainer.querySelector('.welcome-message');
        if (welcomeMsg) {
            welcomeMsg.remove();
        }

        this.chatContainer.appendChild(messageEl);
        this.chatContainer.scrollTop = this.chatContainer.scrollHeight;

        // Store in history
        this.messageHistory.push({ role, content, timestamp: Date.now() });
    }

    renderMarkdown(content) {
        console.log('renderMarkdown called with content:', content ? content.substring(0, 100) + '...' : 'empty');

        if (!content) {
            console.log('Content is empty, returning empty string');
            return '';
        }

        try {
            // Use marked.js for comprehensive markdown rendering
            if (typeof marked !== 'undefined') {
                console.log('Using marked.js to render markdown');
                const html = marked.parse(content);
                console.log('marked.js rendered HTML:', html ? html.substring(0, 200) + '...' : 'empty');

                // Add syntax highlighting to code blocks after rendering
                setTimeout(() => {
                    if (typeof Prism !== 'undefined') {
                        console.log('Applying syntax highlighting with Prism.js');
                        Prism.highlightAll();
                    }
                }, 0);

                return html;
            } else {
                console.warn('marked.js not available, using fallback rendering');
                // Fallback to basic rendering if marked.js is not available
                const fallbackHtml = content
                    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                    .replace(/\*(.*?)\*/g, '<em>$1</em>')
                    .replace(/`(.*?)`/g, '<code>$1</code>')
                    .replace(/\n/g, '<br>');
                console.log('Fallback HTML:', fallbackHtml.substring(0, 200) + '...');
                return fallbackHtml;
            }
        } catch (error) {
            console.error('Error rendering markdown:', error);
            // Return escaped content as fallback
            const escapedContent = content.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
            console.log('Error fallback content:', escapedContent.substring(0, 200) + '...');
            return escapedContent;
        }
    }

    clearProgressContainer() {
        this.currentTasks.clear();
        this.progressContainer.innerHTML = '<div class="no-tasks-message"><p>No active tasks</p></div>';
    }

    renderProgressCard(task) {
        const existingCard = document.getElementById(`task-${task.id}`);
        if (existingCard) {
            this.updateProgressCard(task);
            return;
        }

        // Remove no-tasks message
        const noTasksMsg = this.progressContainer.querySelector('.no-tasks-message');
        if (noTasksMsg) {
            noTasksMsg.remove();
        }

        const cardEl = document.createElement('div');
        cardEl.className = 'progress-card';
        cardEl.id = `task-${task.id}`;

        const taskId = task.id;
        cardEl.addEventListener('click', () => {
            const latestTask = this.currentTasks.get(taskId);
            if (latestTask) {
                this.openTaskModal(latestTask);
            }
        });

        cardEl.innerHTML = `
            <div class="progress-header">
                <span class="progress-title">${task.title}</span>
                <span class="progress-status ${task.status}">${this.getStatusText(task.status)}</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: ${task.progress}%"></div>
            </div>
            <div class="progress-stats">
                <span>Progress: ${task.progress}%</span>
                <span>${task.duration ? `${task.duration}ms` : 'Running...'}</span>
            </div>
        `;

        this.progressContainer.appendChild(cardEl);
    }

    updateProgressCard(task) {
        const cardEl = document.getElementById(`task-${task.id}`);
        if (!cardEl) return;

        const statusEl = cardEl.querySelector('.progress-status');
        const fillEl = cardEl.querySelector('.progress-fill');
        const statsEl = cardEl.querySelector('.progress-stats');

        statusEl.textContent = this.getStatusText(task.status);
        statusEl.className = `progress-status ${task.status}`;
        fillEl.style.width = `${task.progress}%`;

        const duration = task.duration ? `${task.duration}ms` : 'Running...';
        statsEl.innerHTML = `
            <span>Progress: ${task.progress}%</span>
            <span>${duration}</span>
        `;
    }

    getStatusText(status) {
        const statusMap = {
            'running': '🔄 Running',
            'completed': '✅ Completed',
            'failed': '❌ Failed',
            'cancelled': '⏹️ Cancelled'
        };
        return statusMap[status] || status;
    }

    openTaskModal(task) {
        if (!task) return;

        this.activeModalTaskId = task.id;
        this.taskModal.classList.add('active');
        setTimeout(() => {
            const latestTask = this.currentTasks.get(task.id);
            this.populateTaskModal(latestTask || task);
        }, 0);
        this.switchTab('thinking');
    }

    closeTaskModal() {
        this.taskModal.classList.remove('active');
        this.activeModalTaskId = null;
    }

    refreshTaskModal(task, options = {}) {
        if (!task) return;

        const { force = false } = options;

        if (!force && !this.taskModal.classList.contains('active')) return;
        if (!force && this.activeModalTaskId !== task.id) return;

        this.populateTaskModal(task);
    }

    populateTaskModal(task) {
        if (!task) return;

        this.taskModalTitle.textContent = `${task.title} - Details`;
        this.thinkingContent.textContent = task.thinking || 'No thinking content available';

        const contentHtml = task.content ? this.renderMarkdown(task.content) : '';
        this.contentContent.innerHTML = contentHtml || '<p>No content available</p>';

        const metadataText = task.metadata && Object.keys(task.metadata).length > 0
            ? JSON.stringify(task.metadata, null, 2)
            : 'No metadata available';
        this.metadataContent.textContent = metadataText;
    }

    switchTab(tabName) {
        // Update tab buttons
        this.tabBtns.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tabName);
        });

        // Update tab content
        document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.toggle('active', content.id === `${tabName}-tab`);
        });
    }

    openSettingsModal() {
        this.settingsModal.classList.add('active');
        if (this.profileSelect && this.activeProfileName) {
            this.profileSelect.value = this.activeProfileName;
            this.handleProfileSelectionChange();
        }
    }

    closeSettingsModal() {
        this.settingsModal.classList.remove('active');
    }

    saveSettings() {
        // TODO: Implement settings save functionality
        console.log('Settings saved');
        this.closeSettingsModal();
    }

    clearChat() {
        this.chatContainer.innerHTML = `
            <div class="welcome-message">
                <h2>🤖 Welcome to LLM Pro Mode</h2>
                <p>Send a message to start parallel LLM processing with real-time task monitoring.</p>
            </div>
        `;
        this.messageHistory = [];
    }

    updateConnectionStatus(status, text) {
        this.statusIndicator.className = `status-indicator ${status}`;
        this.statusText.textContent = text;
    }

    updateMonitorStatus(status) {
        this.monitorStatus.textContent = status;
    }

    setSendButtonState(enabled) {
        this.sendBtn.disabled = !enabled;
        this.sendBtn.querySelector('.btn-text').textContent = enabled ? 'Send' : 'Processing...';
    }

    updateTaskStats() {
        const completedTasks = Array.from(this.currentTasks.values()).filter(t => t.status === 'completed');
        const cancelledTasks = Array.from(this.currentTasks.values()).filter(t => t.status === 'cancelled');

        this.stats.totalTasks = this.currentTasks.size;
        const denominator = this.stats.totalTasks - cancelledTasks.length;
        this.stats.successRate = denominator > 0 ?
            (completedTasks.length / denominator) * 100 : 0;

        if (completedTasks.length > 0) {
            this.stats.avgTime = completedTasks.reduce((sum, task) => sum + (task.duration || 0), 0) / completedTasks.length;
        } else {
            this.stats.avgTime = 0;
        }

        this.updateStatisticsDisplay();
    }

    updateStatistics(serverStats) {
        if (serverStats.total_tokens) this.stats.totalTokens = serverStats.total_tokens;
        if (serverStats.avg_duration_ms) this.stats.avgTime = serverStats.avg_duration_ms;
        if (serverStats.success_rate) this.stats.successRate = serverStats.success_rate * 100;
        if (serverStats.total_tasks) this.stats.totalTasks = serverStats.total_tasks;

        this.updateStatisticsDisplay();
    }

    updateStatisticsDisplay() {
        this.totalTokensEl.textContent = this.stats.totalTokens.toLocaleString();
        this.avgTimeEl.textContent = `${Math.round(this.stats.avgTime)}ms`;
        this.successRateEl.textContent = `${Math.round(this.stats.successRate)}%`;
        this.totalTasksEl.textContent = this.stats.totalTasks;
    }
}

// Initialize the application when the DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.llmProApp = new LLMProWebApp();
});

// Handle page visibility changes to pause/resume WebSocket
document.addEventListener('visibilitychange', () => {
    if (window.llmProApp) {
        if (document.hidden) {
            console.log('Page hidden, WebSocket will continue in background');
        } else {
            console.log('Page visible, checking WebSocket connection');
            if (!window.llmProApp.isConnected) {
                window.llmProApp.connectWebSocket();
            }
        }
    }
});
