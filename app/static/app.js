/* noapi Dashboard */

let currentTab = 'jobs';
let currentJobId = null;
let pollTimer = null;

// --- API helper ---
async function api(path, options = {}) {
    const resp = await fetch('/api' + path, options);
    if (!resp.ok) {
        const text = await resp.text();
        throw new Error(text || resp.statusText);
    }
    return resp.json();
}

// --- Tab switching ---
function switchTab(tab) {
    if (!tab || !document.getElementById('tab-' + tab)) tab = 'jobs';
    currentTab = tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.toggle('active', c.id === 'tab-' + tab));
    if (tab === 'plugins') refreshPlugins();
}

// --- Time formatting ---
function timeAgo(isoStr) {
    if (!isoStr) return '-';
    const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
    if (diff < 60) return Math.floor(diff) + 's ago';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
}

function shortId(id) { return id ? id.substring(0, 8) : '-'; }

function badge(status) {
    const cls = 'badge badge-' + (status || 'queued').replace('_', '-');
    return '<span class="' + cls + '">' + (status || 'unknown') + '</span>';
}

// --- Jobs ---
async function refreshJobs() {
    try {
        const jobs = await api('/jobs');
        const tbody = document.getElementById('jobs-tbody');
        if (!jobs.length) {
            tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No jobs yet. Upload a job spec to get started.</td></tr>';
            return;
        }
        tbody.innerHTML = jobs.map(j => {
            const total = j.total_tasks || 1;
            const pct = Math.round((j.completed_tasks / total) * 100);
            return '<tr onclick="showJobDetail(\'' + j.id + '\')">'
                + '<td>' + (j.project_name || shortId(j.id)) + '</td>'
                + '<td>' + badge(j.status) + '</td>'
                + '<td><div class="progress-bar"><div class="progress-fill" style="width:' + pct + '%"></div></div></td>'
                + '<td>' + (j.total_tasks - j.completed_tasks - j.failed_tasks) + '</td>'
                + '<td>-</td>'
                + '<td>' + j.completed_tasks + '</td>'
                + '<td>' + j.failed_tasks + '</td>'
                + '<td>' + timeAgo(j.created_at) + '</td>'
                + '</tr>';
        }).join('');
    } catch (e) { console.error('Failed to refresh jobs:', e); }
}

async function showJobDetail(jobId) {
    currentJobId = jobId;
    document.getElementById('jobs-list-view').style.display = 'none';
    document.getElementById('job-detail-view').style.display = 'block';
    await refreshJobDetail(jobId);
}

function showJobsList() {
    currentJobId = null;
    document.getElementById('jobs-list-view').style.display = 'block';
    document.getElementById('job-detail-view').style.display = 'none';
}

async function refreshJobDetail(jobId) {
    try {
        const job = await api('/jobs/' + jobId);
        const tasks = await api('/tasks?job_id=' + jobId);
        const artifacts = await api('/artifacts?job_id=' + jobId);

        // Job header
        const total = job.total_tasks || 1;
        const pct = Math.round((job.completed_tasks / total) * 100);
        document.getElementById('job-header').innerHTML =
            '<div class="job-header">'
            + '<div><div class="job-title">' + (job.project_name || shortId(job.id)) + '</div>'
            + '<div class="job-meta">ID: ' + job.id + ' | Created: ' + timeAgo(job.created_at) + '</div></div>'
            + '<div style="display:flex;gap:0.5rem;align-items:center">' + badge(job.status)
            + (job.status === 'active' ? ' <button class="btn btn-danger btn-sm" onclick="cancelJob(\'' + job.id + '\')">Cancel</button>' : '')
            + '</div></div>';

        // Needs human section
        const needsHuman = tasks.filter(t => t.status === 'needs_human');
        const nhSection = document.getElementById('needs-human-section');
        if (needsHuman.length) {
            nhSection.innerHTML = '<div class="needs-human-card"><h3>Needs Human Intervention (' + needsHuman.length + ')</h3>'
                + needsHuman.map(t => {
                    return '<div class="needs-human-item">'
                        + '<div class="error-msg"><strong>' + t.task_type + '</strong> (attempt ' + t.attempts + '/' + t.max_attempts + ')<br>'
                        + (t.last_error || 'Unknown error')
                        + '<br><button class="btn btn-warning btn-sm" style="margin-top:0.5rem" onclick="retryTask(\'' + t.id + '\')">Retry</button></div>'
                        + '</div>';
                }).join('')
                + '</div>';
        } else {
            nhSection.innerHTML = '';
        }

        // Tasks table
        document.getElementById('tasks-tbody').innerHTML = tasks.map(t =>
            '<tr><td>' + shortId(t.id) + '</td>'
            + '<td>' + t.task_type + '</td>'
            + '<td>' + badge(t.status) + '</td>'
            + '<td>' + (t.assigned_worker_id ? shortId(t.assigned_worker_id) : '-') + '</td>'
            + '<td>' + t.attempts + '/' + t.max_attempts + '</td>'
            + '<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + (t.last_error || '-') + '</td>'
            + '<td>' + (t.status === 'needs_human' || t.status === 'failed' ? '<button class="btn btn-primary btn-sm" onclick="retryTask(\'' + t.id + '\')">Retry</button>' : '-') + '</td>'
            + '</tr>'
        ).join('');

        // Artifacts grid
        const grid = document.getElementById('artifacts-grid');
        if (!artifacts.length) {
            grid.innerHTML = '<div class="empty-state">No artifacts yet.</div>';
        } else {
            grid.innerHTML = artifacts.map(a => {
                let preview = '';
                if (a.kind === 'image' || (a.filepath && /\.(png|jpg|jpeg|gif|webp)$/i.test(a.filepath))) {
                    preview = '<img src="/api/artifacts/' + a.id + '/download" loading="lazy" alt="artifact">';
                } else if (a.kind === 'video' || (a.filepath && /\.(mp4|webm)$/i.test(a.filepath))) {
                    preview = '<video src="/api/artifacts/' + a.id + '/download" controls></video>';
                } else {
                    preview = '<div style="height:150px;display:flex;align-items:center;justify-content:center;background:var(--bg-tertiary);color:var(--text-muted)">File</div>';
                }
                return '<div class="artifact-card">' + preview
                    + '<div class="artifact-info">'
                    + (a.original_filename || shortId(a.id)) + '<br>'
                    + (a.file_size_bytes ? Math.round(a.file_size_bytes / 1024) + ' KB' : '') + ' '
                    + (a.is_duplicate ? '<span class="badge badge-queued">dup</span>' : '')
                    + '<br><a href="/api/artifacts/' + a.id + '/download" download>Download</a>'
                    + '</div></div>';
            }).join('');
        }
    } catch (e) { console.error('Failed to refresh job detail:', e); }
}

async function cancelJob(jobId) {
    try {
        await api('/jobs/' + jobId + '/cancel', { method: 'POST' });
        await refreshJobDetail(jobId);
    } catch (e) { alert('Cancel failed: ' + e.message); }
}

async function retryTask(taskId) {
    try {
        await api('/tasks/' + taskId + '/retry', { method: 'POST' });
        if (currentJobId) await refreshJobDetail(currentJobId);
    } catch (e) { alert('Retry failed: ' + e.message); }
}

// --- Upload ---
function setupUpload() {
    const area = document.getElementById('upload-area');
    const input = document.getElementById('job-file');
    const feedback = document.getElementById('upload-feedback');

    area.addEventListener('dragover', e => { e.preventDefault(); area.classList.add('dragover'); });
    area.addEventListener('dragleave', () => area.classList.remove('dragover'));
    area.addEventListener('drop', e => {
        e.preventDefault();
        area.classList.remove('dragover');
        if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]);
    });
    input.addEventListener('change', () => { if (input.files.length) handleFile(input.files[0]); });

    async function handleFile(file) {
        feedback.innerHTML = '';
        try {
            const text = await file.text();
            const spec = JSON.parse(text);
            const result = await api('/jobs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(spec),
            });
            feedback.innerHTML = '<div class="feedback-success">Job created: ' + (result.project_name || result.id) + ' (' + result.total_tasks + ' tasks)</div>';
            await refreshJobs();
        } catch (e) {
            feedback.innerHTML = '<div class="feedback-error">Error: ' + e.message + '</div>';
        }
    }
}

// --- Workers ---
async function refreshWorkers() {
    try {
        const workers = await api('/workers');
        const tbody = document.getElementById('workers-tbody');
        if (!workers.length) {
            tbody.innerHTML = '<tr><td colspan="5" class="empty-state">No workers registered.</td></tr>';
            return;
        }
        tbody.innerHTML = workers.map(w => {
            const lastSeen = w.last_seen_at ? new Date(w.last_seen_at) : null;
            const stale = !lastSeen || (Date.now() - lastSeen.getTime()) > 120000;
            return '<tr>'
                + '<td>' + w.worker_id + '</td>'
                + '<td>' + (w.hostname || '-') + '</td>'
                + '<td>' + (w.plugin || '-') + '</td>'
                + '<td>' + timeAgo(w.last_seen_at) + '</td>'
                + '<td><span class="' + (stale ? 'status-stale' : 'status-online') + '">' + (stale ? 'stale' : 'online') + '</span></td>'
                + '</tr>';
        }).join('');
    } catch (e) { console.error('Failed to refresh workers:', e); }
}

// --- Plugins ---
async function refreshPlugins() {
    try {
        const plugins = await api('/plugins');
        const container = document.getElementById('plugins-container');
        if (!plugins.length) {
            container.innerHTML = '<div class="empty-state">No plugins registered. Start a worker to register its plugin.</div>';
            return;
        }
        container.innerHTML = plugins.map(p => {
            const taskTypes = (p.capabilities && p.capabilities.task_types) || [];
            return '<div class="plugin-card">'
                + '<h3>' + (p.display_name || p.name) + '</h3>'
                + '<div class="version">v' + (p.version || '?') + '</div>'
                + taskTypes.map(tt =>
                    '<div class="task-type"><span class="name">' + tt.name + '</span>'
                    + (tt.description ? '<br>' + tt.description : '')
                    + '</div>'
                ).join('')
                + '</div>';
        }).join('');
    } catch (e) { console.error('Failed to refresh plugins:', e); }
}

// --- Polling ---
function startPolling() {
    async function poll() {
        await refreshJobs();
        await refreshWorkers();
        if (currentJobId) await refreshJobDetail(currentJobId);
    }
    poll();
    pollTimer = setInterval(poll, 3000);
}

// --- Init ---
document.addEventListener('DOMContentLoaded', () => {
    setupUpload();
    switchTab(location.hash.slice(1) || 'jobs');
    startPolling();
});
window.addEventListener('hashchange', () => switchTab(location.hash.slice(1) || 'jobs'));
