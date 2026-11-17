/**
 * main.js
 * ────────────────────────────────────────────────────────────
 * Electron entry point for Octis.
 */

const { app, BrowserWindow, shell, Menu, dialog, powerMonitor } = require('electron');
const { spawn, execFile, execFileSync } = require('child_process');
const path                           = require('path');
const http                           = require('http');
const fs                             = require('fs');
const os                             = require('os');
const { autoUpdater }                = require('electron-updater');

let mainWindow    = null;
let pythonProcess = null;
let pythonExited  = false;   // backend died before/after starting
let pythonStderr  = '';      // last bit of backend error output, for the log
let pythonStopped = false;   // set once we've cleanly shut the backend down
let pendingUpdate = null;    // info about an update that's downloaded and ready

// Name of the installer electron-updater downloads and runs.
// Must match "artifactName" in package.json (win section).
const INSTALLER_EXE = 'Quick-Notes-Setup.exe';

// ── Update logging ────────────────────────────────────────────
// Writes update activity to Documents/Octis/update.log so we can
// see exactly what the auto-updater is doing (or why it fails).
function updateLog(msg) {
  try {
    const dir = path.join(os.homedir(), 'Documents', 'Octis');
    fs.mkdirSync(dir, { recursive: true });
    const line = `[${new Date().toISOString()}] ${msg}\n`;
    fs.appendFileSync(path.join(dir, 'update.log'), line);
  } catch (e) { /* ignore */ }
}

// ── Only one copy of the app at a time ────────────────────────
// Two copies would fight over port 5000 and over the app's files
// while an update is installing. A second launch just focuses the
// window that's already open.
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
  app.exit(0);
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });
}

// ── Is an update being installed right now? ───────────────────
// When the app closes with an update waiting, the installer runs in
// the background for ~10-30 seconds while it swaps the app's files.
// If the user opens the app during that window, the backend starts
// from half-replaced files and crashes ("PortAudio library not
// found"), and our open files can also make the install fail.
function isInstallerRunning() {
  if (process.platform !== 'win32' || !app.isPackaged) return false;
  try {
    const out = execFileSync(
      'tasklist',
      ['/FI', `IMAGENAME eq ${INSTALLER_EXE}`, '/NH'],
      { windowsHide: true, encoding: 'utf8', timeout: 5000 }
    );
    return out.toLowerCase().includes(INSTALLER_EXE.toLowerCase());
  } catch (e) {
    return false;
  }
}

// Get out of the installer's way, and reopen the app by ourselves as
// soon as the installer finishes (gives up after ~3 minutes).
function reopenAfterInstaller() {
  const exe = process.execPath.replace(/'/g, "''");
  const name = INSTALLER_EXE.replace(/\.exe$/i, '');
  const script =
    `$i = 0; ` +
    `while ((Get-Process -Name '${name}' -ErrorAction SilentlyContinue) -and ($i -lt 180)) ` +
    `{ Start-Sleep -Seconds 1; $i++ }; ` +
    `Start-Sleep -Seconds 2; ` +
    `Start-Process -FilePath '${exe}'`;
  try {
    spawn('powershell.exe',
      ['-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', script],
      { detached: true, stdio: 'ignore', windowsHide: true }
    ).unref();
  } catch (e) {
    updateLog('Could not schedule reopen after install: ' + e.message);
  }
}

// Wait (without freezing anything) until the installer has closed.
// Returns true if it finished, false if we gave up after maxSeconds.
async function waitForInstallerToFinish(maxSeconds) {
  for (let i = 0; i < maxSeconds; i++) {
    if (!isInstallerRunning()) {
      // Small pause so Windows fully releases the installer's files.
      await new Promise(r => setTimeout(r, 1500));
      return true;
    }
    await new Promise(r => setTimeout(r, 1000));
  }
  return false;
}

// ── Auto updater ──────────────────────────────────────────────
// Downloads in the background. When ready, we offer "Restart now"
// (installs + reopens in ~10 seconds) or "Later" (installs the next
// time the user closes the app).
autoUpdater.autoDownload         = true;
autoUpdater.autoInstallOnAppQuit = true;

function setupAutoUpdater() {
  if (!app.isPackaged) {
    updateLog('Not packaged (dev mode) — skipping update check');
    return;
  }
  updateLog('Current version: ' + app.getVersion() + ' — checking for updates...');

  autoUpdater.on('checking-for-update', () => updateLog('Checking for update...'));
  autoUpdater.on('update-available',    (i) => updateLog('Update AVAILABLE: ' + (i && i.version)));
  autoUpdater.on('update-not-available',(i) => updateLog('No update. Server has: ' + (i && i.version)));
  autoUpdater.on('download-progress',   (p) => updateLog('Downloading: ' + Math.round(p.percent) + '%'));
  autoUpdater.on('update-downloaded',   (i) => {
    updateLog('Update DOWNLOADED: ' + (i && i.version) + ' — asking user / will install on next quit');
    pendingUpdate = i || {};
    // If the window isn't up yet, the prompt is shown once it is.
    if (mainWindow && mainWindow.isVisible()) promptToInstallUpdate();
  });
  autoUpdater.on('error', (err) => {
    updateLog('UPDATE ERROR: ' + (err ? err.message : 'unknown'));
  });

  checkForUpdatesNow();

  // Students often leave the app open for days and just close the
  // laptop lid. Without these, we'd only ever check at launch.
  // 1) Check again every 4 hours while the app is open.
  setInterval(checkForUpdatesNow, 4 * 60 * 60 * 1000);
  // 2) Check when the laptop wakes up from sleep (lid opened).
  powerMonitor.on('resume', () => {
    updateLog('Computer woke up — checking for updates');
    // Give Wi-Fi a moment to reconnect first.
    setTimeout(checkForUpdatesNow, 30 * 1000);
  });
}

function checkForUpdatesNow() {
  // Already downloaded and waiting? No need to check again.
  if (pendingUpdate) {
    // If they picked "Later" a while ago, remind them once more on
    // the next check (at most every 4 hours / on wake).
    if (mainWindow && mainWindow.isVisible()) {
      updatePromptShown = false;
      promptToInstallUpdate();
    }
    return;
  }
  autoUpdater.checkForUpdates().catch((err) => {
    updateLog('checkForUpdates threw: ' + (err ? err.message : 'unknown'));
  });
}

let updatePromptShown = false;
let updatePromptTimer = null;
let loggedBusyWait    = false;   // log the wait once, not every 15s

// ── Is the student in the middle of something? ────────────────
// Busy means any of these:
//  - a lecture is recording (paused counts too)
//  - notes are generating, or a request is waiting on Claude
//  - flashcards, cram, a practice test or weak spots are on screen
// If something can't be checked, we treat that part as not busy.
async function isAppBusy() {
  if (await isBackendBusy()) return true;
  return isStudentStudying();
}

function isStudentStudying() {
  if (!mainWindow || mainWindow.isDestroyed()) return Promise.resolve(false);
  return mainWindow.webContents
    .executeJavaScript('typeof window.qnIsStudying === "function" && window.qnIsStudying()', true)
    .then(r => !!r)
    .catch(() => false);
}

function isBackendBusy() {
  return new Promise(resolve => {
    const req = http.get('http://127.0.0.1:5000/api/busy', res => {
      let body = '';
      res.on('data', c => { body += c; });
      res.on('end', () => {
        try { resolve(!!JSON.parse(body).busy); }
        catch (e) { resolve(false); }
      });
    });
    req.on('error', () => resolve(false));
    req.setTimeout(3000, () => { req.destroy(); resolve(true); });
  });
}

// Never pop the update box up while recording or generating. We
// check every 15 seconds, and only show it after the app has been
// idle twice in a row (5 seconds apart), so we don't slip in during
// the moment between pressing Stop and generation starting.
function promptToInstallUpdate() {
  if (!pendingUpdate || updatePromptShown || !mainWindow) return;
  if (updatePromptTimer) return;   // already waiting for idle

  const tryAgainLater = (ms) => {
    updatePromptTimer = setTimeout(() => {
      updatePromptTimer = null;
      promptToInstallUpdate();
    }, ms);
  };

  updatePromptTimer = 'checking';   // blocks a second check starting meanwhile
  isAppBusy().then(busy => {
    updatePromptTimer = null;
    if (busy) {
      if (!loggedBusyWait) updateLog('Update ready, but the student is busy — waiting');
      loggedBusyWait = true;
      return tryAgainLater(15 * 1000);
    }
    updatePromptTimer = setTimeout(() => {
      isAppBusy().then(stillBusy => {
        updatePromptTimer = null;
        if (stillBusy) return tryAgainLater(15 * 1000);
        showUpdatePrompt();
      });
    }, 5 * 1000);
  });
}

function showUpdatePrompt() {
  if (!pendingUpdate || updatePromptShown || !mainWindow) return;
  updatePromptShown = true;

  const handle = (choice) => {
    if (choice === 'restart') installUpdateNow();
    else updateLog('User chose Later — will install on next quit');
  };

  // Show the app's own styled card. If the page can't show it
  // (older page, or it errors), fall back to the plain Windows box.
  const v = pendingUpdate.version || '';
  mainWindow.webContents
    .executeJavaScript(
      'typeof window.qnShowUpdateCard === "function" ? ' +
      `window.qnShowUpdateCard(${JSON.stringify(v)}) : "unsupported"`, true)
    .then(choice => {
      if (choice === 'restart' || choice === 'later') return handle(choice);
      showNativeUpdatePrompt(handle);
    })
    .catch(() => showNativeUpdatePrompt(handle));
}

function showNativeUpdatePrompt(handle) {
  if (!mainWindow) return;
  const version = pendingUpdate && pendingUpdate.version ? ` (v${pendingUpdate.version})` : '';
  dialog.showMessageBox(mainWindow, {
    type:      'none',
    title:     'Update ready',
    message:   `A new version of Quick Notes${version} is ready.`,
    detail:    'Restart now to install it. It only takes a few seconds and ' +
               'Quick Notes will reopen by itself.\n\n' +
               'If you choose Later, it installs the next time you close the app.',
    buttons:   ['Restart now', 'Later'],
    defaultId: 0,
    cancelId:  1,
    noLink:    true,
  }).then(({ response }) => handle(response === 0 ? 'restart' : 'later'))
    .catch(() => {});
}

async function installUpdateNow() {
  updateLog('User chose Restart now — stopping backend and installing');
  // The backend MUST be fully stopped first, or the installer can't
  // replace its files and the update silently fails.
  await stopPython();
  pythonStopped = true;
  // isSilent = true (no installer window), isForceRunAfter = true
  // (installer reopens Quick Notes when it's done).
  autoUpdater.quitAndInstall(true, true);
}

// ── Find the Python backend ───────────────────────────────────
function getPythonPath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'python', 'app.exe');
  } else {
    return 'python';
  }
}

function getPythonArgs() {
  if (app.isPackaged) {
    return [];
  } else {
    return [path.join(__dirname, '..', 'app.py')];
  }
}

// ── Start Flask backend ───────────────────────────────────────
function startPython() {
  const pythonPath = getPythonPath();
  const pythonArgs = getPythonArgs();
  const workingDir = app.isPackaged
    ? path.join(process.resourcesPath, 'python')
    : path.join(__dirname, '..');

  console.log('Starting Python backend:', pythonPath);
  console.log('Working dir:', workingDir);

  pythonExited = false;
  pythonStderr = '';

  pythonProcess = spawn(pythonPath, pythonArgs, {
    cwd: workingDir,
    stdio: 'pipe',
    windowsHide: true,
  });

  pythonProcess.stdout.on('data', d => console.log('[Python]', d.toString()));
  pythonProcess.stderr.on('data', d => {
    const text = d.toString();
    console.error('[Python]', text);
    // Keep only the last few KB so a crash can be written to the log.
    pythonStderr = (pythonStderr + text).slice(-4000);
  });

  pythonProcess.on('error', err => {
    pythonExited = true;
    updateLog('Backend failed to launch: ' + err.message);
  });

  pythonProcess.on('exit', code => {
    pythonExited = true;
    console.log('Python process exited with code', code);
  });
}

// ── Stop Flask backend (and anything it started) ──────────────
// pythonProcess.kill() on Windows only kills app.exe itself and
// returns before it's actually gone. If anything is still running
// when the installer starts, its files stay locked and the update
// fails — which is why updates sometimes needed 2-3 tries.
// taskkill /T kills the whole process tree, and we wait for it.
function stopPython() {
  return new Promise(resolve => {
    const proc = pythonProcess;
    pythonProcess = null;
    if (!proc || proc.exitCode !== null || proc.signalCode !== null) {
      return resolve();
    }

    let finished = false;
    const done = () => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      resolve();
    };
    const timer = setTimeout(done, 5000);   // never hang the quit
    proc.once('exit', done);

    if (process.platform === 'win32') {
      execFile('taskkill', ['/PID', String(proc.pid), '/T', '/F'],
        { windowsHide: true }, () => {});
    } else {
      proc.kill();
    }
  });
}

// ── Wait for Flask to be ready ────────────────────────────────
function waitForFlask(retries = 30, delay = 500) {
  return new Promise((resolve, reject) => {
    let attempts = 0;

    const check = () => {
      if (pythonExited) {
        reject(new Error('Backend exited before it was ready'));
        return;
      }
      http.get('http://127.0.0.1:5000', res => {
        res.resume();
        resolve();
      }).on('error', () => {
        attempts++;
        if (attempts >= retries) {
          reject(new Error('Flask did not start in time'));
        } else {
          setTimeout(check, delay);
        }
      });
    };

    check();
  });
}

// ── Friendly "couldn't start" message ─────────────────────────
// Replaces the raw Python error popup students used to see.
function showStartupError(err) {
  updateLog('STARTUP FAILED: ' + err.message +
    (pythonStderr ? '\n--- backend output ---\n' + pythonStderr.trim() : ''));

  dialog.showMessageBoxSync({
    type:    'warning',
    title:   'Quick Notes',
    message: "Quick Notes couldn't start.",
    detail:  'If Quick Notes was just updating, wait a few seconds and open it again.\n\n' +
             'If this keeps happening, restart your computer and try again.',
    buttons: ['OK'],
    noLink:  true,
  });
}

// ── Create the window ─────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width:           900,
    height:          740,
    minWidth:        640,
    minHeight:       560,
    title:           'Quick Notes',
    backgroundColor: '#F0F2F5',
    autoHideMenuBar: true,
    menuBarVisible:  false,
    icon:            app.isPackaged
                       ? path.join(process.resourcesPath, 'icon.ico')
                       : path.join(__dirname, '..', 'icon.ico'),
    webPreferences: {
      nodeIntegration:  false,
      contextIsolation: true,
      geolocation:      false,
    },
    // Clean frameless feel on Mac
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    show: false,   // don't show until ready
  });

  // Block any permission requests — Octis doesn't need location, camera, etc.
  mainWindow.webContents.session.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(false);
  });

  // Load the Flask app
  mainWindow.loadURL('http://127.0.0.1:5000');

  // Show window once loaded — prevents white flash
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
    // An update may have finished downloading before the window was up.
    promptToInstallUpdate();
  });

  // Open external links in browser, not in the app
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

// ── App lifecycle ─────────────────────────────────────────────
app.whenReady().then(async () => {
  if (!gotSingleInstanceLock) return;

  // Opened while an update is installing? Step aside and reopen
  // automatically once it's done, instead of crashing.
  if (isInstallerRunning()) {
    if (process.argv.includes('--updated')) {
      // The installer opens the app as its very last step, a moment
      // before it closes itself. The files are already in place, so
      // we just wait for it to finish and carry on starting up.
      // (Before 1.3.8 we quit here and relied on a hidden PowerShell
      // script to reopen us. On some PCs that script never ran, so
      // "Restart now" left the app closed.)
      updateLog('Reopened by the update installer — waiting for it to finish');
      const finished = await waitForInstallerToFinish(120);
      updateLog(finished
        ? 'Installer finished — starting up'
        : 'Installer still running after 2 minutes — starting up anyway');
    } else {
      updateLog('Opened while the update installer is running — will reopen when it finishes');
      reopenAfterInstaller();
      pythonStopped = true;
      app.exit(0);
      return;
    }
  }

  Menu.setApplicationMenu(null);
  setupAutoUpdater();
  startPython();

  try {
    await waitForFlask();
    createWindow();
  } catch (err) {
    console.error('Could not connect to Flask:', err.message);
    await stopPython();
    pythonStopped = true;
    showStartupError(err);
    app.quit();
  }
});

app.on('window-all-closed', () => {
  // The backend is stopped in 'before-quit' below.
  app.quit();
});

// Fully stop the backend BEFORE the app finishes quitting. The
// updater runs the installer right after this, and it needs every
// file unlocked to install the update on the first try.
app.on('before-quit', (event) => {
  if (pythonStopped) return;
  event.preventDefault();
  stopPython().then(() => {
    pythonStopped = true;
    app.quit();
  });
});

app.on('activate', () => {
  // Mac: re-open window when clicking dock icon
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

// Last-resort cleanup if Electron crashes or is force-quit
process.on('exit', () => {
  if (pythonProcess && pythonProcess.exitCode === null) {
    try {
      if (process.platform === 'win32') {
        execFileSync('taskkill', ['/PID', String(pythonProcess.pid), '/T', '/F'],
          { windowsHide: true, stdio: 'ignore', timeout: 3000 });
      } else {
        pythonProcess.kill();
      }
    } catch (e) { /* already gone */ }
  }
});
