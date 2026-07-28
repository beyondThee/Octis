/**
 * main.js
 * ────────────────────────────────────────────────────────────
 * Electron entry point for Octis.
 */

const { app, BrowserWindow, shell, Menu } = require('electron');
const { spawn }                      = require('child_process');
const path                           = require('path');
const http                           = require('http');
const fs                             = require('fs');
const os                             = require('os');
const { autoUpdater }                = require('electron-updater');

let mainWindow   = null;
let pythonProcess = null;

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
    updateLog('Update DOWNLOADED: ' + (i && i.version) + ' — installing on quit');
    autoUpdater.quitAndInstall(true, true);
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

  pythonProcess = spawn(pythonPath, pythonArgs, {
    cwd: workingDir,
    stdio: 'pipe',
    windowsHide: true,
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
      http.get('http://127.0.0.1:5000', res => {
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
  Menu.setApplicationMenu(null);
  setupAutoUpdater();
  startPython();

  try {
    await waitForFlask();
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
