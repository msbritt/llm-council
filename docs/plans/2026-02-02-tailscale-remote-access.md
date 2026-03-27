# Tailscale Remote Access Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable web UI access from a second machine over Tailscale network by configuring CORS, dev server bindings, and API endpoint resolution.

**Architecture:** Currently the backend binds to 0.0.0.0:8001 but CORS restricts to localhost origins. Frontend dev server only binds to localhost and hardcodes API_BASE to localhost. We'll add Tailscale-accessible origins to CORS, bind Vite to all interfaces, and make API endpoint configurable via environment variable.

**Tech Stack:** FastAPI (backend), Vite+React (frontend), Tailscale networking

---

## Pre-Implementation Context

**Current Setup:**
- Backend: FastAPI on 0.0.0.0:8001 (good - already accessible)
- Frontend: Vite dev server on localhost:5173 (bad - not accessible)
- API endpoint: Hardcoded to `http://localhost:8001` (bad - not flexible)
- CORS: Only allows localhost origins (bad - blocks Tailscale)

**Tailscale Info:**
- Dev machine hostname: `wintermute` (IP: 100.101.32.50)
- Access will be via: `http://wintermute:5173` and `http://wintermute:8001`

**Files to Modify:**
- `backend/main.py` - Add Tailscale origins to CORS
- `frontend/vite.config.js` - Bind dev server to 0.0.0.0
- `frontend/src/api.js` - Make API_BASE configurable
- `frontend/.env.example` - Document environment variable (new file)

---

## Task 1: Update Backend CORS Configuration

**Files:**
- Modify: `backend/main.py:29-35`

**Step 1: Read current CORS configuration**

Run: `cat backend/main.py | grep -A 10 "CORSMiddleware"`

Expected: See current allow_origins with only localhost entries

**Step 2: Update CORS to include Tailscale origins**

Edit `backend/main.py` line 31, change:
```python
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
```

To:
```python
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://wintermute:5173",
        "http://100.101.32.50:5173",
    ],
```

**Step 3: Verify the change**

Run: `cat backend/main.py | grep -A 10 "CORSMiddleware"`

Expected: See 4 origins including wintermute and IP

**Step 4: Test backend still starts**

Run: `cd backend && python -m backend.main &`

Expected: Server starts on 0.0.0.0:8001 without errors

Run: `pkill -f "backend.main"` to stop

**Step 5: Commit**

```bash
git add backend/main.py
git commit -m "feat: add Tailscale origins to CORS for remote access"
```

---

## Task 2: Configure Vite Dev Server for Network Access

**Files:**
- Modify: `frontend/vite.config.js:1-7`

**Step 1: Read current Vite config**

Run: `cat frontend/vite.config.js`

Expected: See minimal config without server section

**Step 2: Add server configuration to bind to all interfaces**

Edit `frontend/vite.config.js`, change:
```javascript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
})
```

To:
```javascript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',  // Listen on all network interfaces for Tailscale access
    port: 5173,
  }
})
```

**Step 3: Verify the change**

Run: `cat frontend/vite.config.js`

Expected: See server section with host: '0.0.0.0'

**Step 4: Test dev server binds to all interfaces**

Run: `cd frontend && npm run dev`

Expected: Output shows "Network: use --host to expose" or shows network address

Press Ctrl+C to stop

**Step 5: Commit**

```bash
git add frontend/vite.config.js
git commit -m "feat: configure Vite to listen on all interfaces for remote access"
```

---

## Task 3: Make Frontend API Endpoint Configurable

**Files:**
- Modify: `frontend/src/api.js:5`

**Step 1: Read current API configuration**

Run: `head -10 frontend/src/api.js`

Expected: See hardcoded `const API_BASE = 'http://localhost:8001';`

**Step 2: Make API_BASE configurable via environment variable**

Edit `frontend/src/api.js` line 5, change:
```javascript
const API_BASE = 'http://localhost:8001';
```

To:
```javascript
const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8001';
```

**Step 3: Verify the change**

Run: `head -10 frontend/src/api.js`

Expected: See environment variable with fallback to localhost

**Step 4: Test that default still works**

Run: `cd frontend && npm run dev`

Expected: No errors, app starts normally

Press Ctrl+C to stop

**Step 5: Commit**

```bash
git add frontend/src/api.js
git commit -m "feat: make API endpoint configurable via VITE_API_BASE env var"
```

---

## Task 4: Create Environment Variable Documentation

**Files:**
- Create: `frontend/.env.example`

**Step 1: Create example environment file**

Create `frontend/.env.example` with content:
```bash
# API Backend Configuration
# For local development, omit this to use the default (http://localhost:8001)
# For remote access via Tailscale, set to your dev machine's Tailscale hostname or IP
# Example: VITE_API_BASE=http://wintermute:8001
# Example: VITE_API_BASE=http://100.101.32.50:8001

# VITE_API_BASE=http://localhost:8001
```

**Step 2: Verify file exists and is readable**

Run: `cat frontend/.env.example`

Expected: See documentation with examples

**Step 3: Update CLAUDE.md with new configuration**

Read current configuration section:

Run: `grep -A 20 "Port Configuration" CLAUDE.md`

Add new section after "Port Configuration" in CLAUDE.md:

```markdown
### Remote Access Configuration
For accessing the web UI from another machine on Tailscale:

**Backend (already configured):**
- Binds to 0.0.0.0:8001 (accessible from network)
- CORS allows wintermute:5173 and 100.101.32.50:5173

**Frontend:**
- Dev server binds to 0.0.0.0:5173 (accessible from network)
- API endpoint configurable via `VITE_API_BASE` environment variable

**Setup on remote machine:**
1. SSH to dev machine and attach to tmux session
2. Ensure backend/frontend are running
3. On local machine, access: `http://wintermute:5173`

**Setup to work from remote machine:**
1. Clone repo on remote machine
2. Create `frontend/.env.local` with:
   ```
   VITE_API_BASE=http://wintermute:8001
   ```
3. Run frontend locally, connects to remote backend
```

**Step 4: Commit**

```bash
git add frontend/.env.example CLAUDE.md
git commit -m "docs: add environment variable example and remote access guide"
```

---

## Task 5: Integration Testing

**Files:**
- Test: All modified files working together

**Step 1: Start backend in background**

Run: `cd backend && python -m backend.main > /tmp/backend.log 2>&1 &`

Save PID: `echo $! > /tmp/backend.pid`

**Step 2: Verify backend is listening**

Run: `sleep 2 && curl -s http://localhost:8001/ | jq .`

Expected: `{"status": "ok", "service": "LLM Council API"}`

**Step 3: Start frontend in background**

Run: `cd frontend && npm run dev > /tmp/frontend.log 2>&1 &`

Save PID: `echo $! > /tmp/frontend.pid`

**Step 4: Verify frontend is accessible on network**

Run: `sleep 3 && curl -s http://100.101.32.50:5173/ | head -5`

Expected: HTML content with DOCTYPE

**Step 5: Check both services are running**

Run: `ps aux | grep -E "(backend.main|vite)" | grep -v grep`

Expected: See both processes running

**Step 6: Stop test services**

Run: `kill $(cat /tmp/backend.pid) $(cat /tmp/frontend.pid) 2>/dev/null; rm /tmp/*.pid /tmp/*.log`

**Step 7: Document testing in commit message**

```bash
git add -A
git commit -m "test: verify backend and frontend accessible on Tailscale network

- Backend CORS allows wintermute origins
- Frontend dev server binds to 0.0.0.0
- API endpoint configurable for remote access
- Integration test confirms network accessibility"
```

---

## Task 6: Update Project Documentation

**Files:**
- Modify: `README.md` (if exists) or `CLAUDE.md`

**Step 1: Check if README exists**

Run: `test -f README.md && echo "EXISTS" || echo "NOT FOUND"`

**Step 2: Add remote access section to CLAUDE.md**

Add to "Common Gotchas" section in CLAUDE.md:

```markdown
4. **Tailscale Remote Access**: When accessing UI from second machine:
   - Backend already accessible (binds to 0.0.0.0)
   - Frontend needs `npm run dev` running on dev machine
   - Access via `http://wintermute:5173` or `http://100.101.32.50:5173`
   - Create `frontend/.env.local` if running frontend on remote machine:
     ```
     VITE_API_BASE=http://wintermute:8001
     ```
```

**Step 3: Verify documentation is clear**

Run: `grep -A 10 "Tailscale Remote Access" CLAUDE.md`

Expected: See clear instructions for remote access

**Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add Tailscale remote access to common gotchas"
```

---

## Post-Implementation Validation

**Manual Testing Checklist:**

1. **Local Access (unchanged):**
   - [ ] Backend starts: `python -m backend.main`
   - [ ] Frontend starts: `cd frontend && npm run dev`
   - [ ] Access `http://localhost:5173` - works
   - [ ] Create conversation, send message - works

2. **Remote Access from Second Machine:**
   - [ ] SSH to dev machine, attach tmux
   - [ ] Backend/frontend running in tmux
   - [ ] From second machine, access `http://wintermute:5173`
   - [ ] UI loads correctly
   - [ ] Create conversation, send message - works
   - [ ] Check browser console - no CORS errors

3. **Configuration Validation:**
   - [ ] `frontend/.env.example` documents VITE_API_BASE
   - [ ] CLAUDE.md updated with remote access info
   - [ ] All commits have descriptive messages

**Rollback Plan:**

If something breaks:
```bash
git log --oneline -6
git revert <commit-hash>  # Revert specific change
```

Or reset all changes:
```bash
git reset --hard HEAD~6  # Remove all 6 commits from this plan
```

---

## Success Criteria

- ✅ Backend accepts requests from Tailscale origins
- ✅ Frontend dev server accessible from network
- ✅ API endpoint configurable for different scenarios
- ✅ Documentation clear for future development sessions
- ✅ No breaking changes to local development workflow
- ✅ All changes committed with clear messages

---

## Notes for Future Enhancement

- Consider adding authentication/authorization for remote access
- Could use environment detection to auto-configure API_BASE
- May want to use Tailscale's serve/funnel features for HTTPS
- Could add nginx reverse proxy for production-like setup
