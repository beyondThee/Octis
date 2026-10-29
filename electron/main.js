/**
 * main.js
 * ────────────────────────────────────────────────────────────
 * Electron entry point for Octis.
 */

const { app, BrowserWindow, shell, Menu } = require('electron');
const { spawn }                      = require('child_process');
const path                           = require('path');
const http                           = require('http');
const net                            = require('net');
const fs                             = require('fs');
const os                             = require('os');
const { autoUpdater }                = require('electron-updater');

const IS_MAC = process.platform === 'darwin';

let mainWindow   = null;
let pythonProcess = null;

// ── Backend port ──────────────────────────────────────────────
// Windows keeps 5000. On Mac, AirPlay Receiver (macOS 12+) already
// listens on 5000, so we'd load Apple's error page instead of ours.
// The port must stay the same between launches: theme and sound
// settings live in localStorage, which is tied to the exact address.
const PREFERRED_PORT = IS_MAC ? 5179 : 5000;
let flaskPort = PREFERRED_PORT;

// Resolves true if nothing else is listening on the port.
function isPortFree(port) {
  return new Promise(resolve => {
    const srv = net.createServer();
    srv.once('error', () => resolve(false));
    srv.once('listening', () => srv.close(() => resolve(true)));
    srv.listen(port, '127.0.0.1');
  });
}

// Asks the OS for any free port. Only used on Mac if the preferred
// one is taken, so the app still opens instead of quitting.
function getRandomFreePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

async function pickPort() {
  if (!IS_MAC) return PREFERRED_PORT;
  if (await isPortFree(PREFERRED_PORT)) return PREFERRED_PORT;
  return getRandomFreePort();
}

function flaskUrl() {
  return `http://127.0.0.1:${flaskPort}`;
}

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

// ── Silent auto updater ───────────────────────────────────────
// v1.1.4: verifying clean install-on-quit (no mid-use interruption)
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
    // Do NOT force-quit here — that interrupts the user mid-task.
    // autoInstallOnAppQuit (set above) installs it silently the next
    // time they close the app on their own. Seamless, no disruption.
    updateLog('Update DOWNLOADED: ' + (i && i.version) + ' — will install on next quit');
  });
  autoUpdater.on('error', (err) => {
    updateLog('UPDATE ERROR: ' + (err ? err.message : 'unknown'));
  });

  autoUpdater.checkForUpdates().catch((err) => {
    updateLog('checkForUpdates threw: ' + (err ? err.message : 'unknown'));
  });
}

// ── Find the Python backend ───────────────────────────────────
function getPythonPath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'python', IS_MAC ? 'app' : 'app.exe');
  } else {
    return IS_MAC ? 'python3' : 'python';
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

  pythonProcess = spawn(pythonPath, pythonArgs, {
    cwd: workingDir,
    stdio: 'pipe',
    windowsHide: true,
    env: { ...process.env, QN_PORT: String(flaskPort) },
  });

  pythonProcess.stdout.on('data', d => console.log('[Python]', d.toString()));
  pythonProcess.stderr.on('data', d => console.error('[Python]', d.toString()));

  pythonProcess.on('exit', code => {
    console.log('Python process exited with code', code);
  });
}

// ── Wait for Flask to be ready ────────────────────────────────
function waitForFlask(retries = 30, delay = 500) {
  return new Promise((resolve, reject) => {
    let attempts = 0;

    const check = () => {
      http.get(flaskUrl(), res => {
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
    // Mac takes its icon from the app bundle, not the window
    icon:            IS_MAC ? undefined
                   : app.isPackaged
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
  // (The microphone is used by the Python backend, not this window.)
  mainWindow.webContents.session.setPermissionRequestHandler((webContents, permission, callback) => {
    callback(false);
  });

  // Load the Flask app
  mainWindow.loadURL(flaskUrl());

  // Show window once loaded — prevents white flash
  mainWindow.once('ready-to-show', () => {
    mainWindow.show();
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
// Mac keeps Copy, Paste, Undo and Quit in the menu bar, so removing
// the menu would break Cmd+C / Cmd+V / Cmd+Z / Cmd+Q. Windows has no
// menu, same as before.
function setupMenu() {
  if (!IS_MAC) {
    Menu.setApplicationMenu(null);
    return;
  }
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { role: 'appMenu' },
    { role: 'editMenu' },
    { role: 'windowMenu' },
  ]));
}

app.whenReady().then(async () => {
  setupMenu();
  setupAutoUpdater();
  flaskPort = await pickPort();
  startPython();

  try {
    // First launch on a Mac is slow: macOS security-scans every file in
    // the bundle before the backend can start. Give it a full minute.
    await waitForFlask(IS_MAC ? 120 : 30);
    createWindow();
  } catch (err) {
    console.error('Could not connect to Flask:', err.message);
    app.quit();
  }
});

app.on('window-all-closed', () => {
  // Kill Python when all windows are closed
  if (pythonProcess) {
    pythonProcess.kill();
    pythonProcess = null;
  }
  app.quit();
});

app.on('activate', () => {
  // Mac: re-open window when clicking dock icon
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

// Kill Python if Electron crashes or is force-quit
process.on('exit', () => {
  if (pythonProcess) pythonProcess.kill();
});
