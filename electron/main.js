const { app, BrowserWindow, dialog, shell } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const http = require('http')
const { autoUpdater } = require('electron-updater')

const PORT = 8000
const isDev = !app.isPackaged

let backendProcess = null
let mainWindow = null
let splashWindow = null

function getBackendPath() {
  if (isDev) {
    return null // 开发模式：手动启动 uvicorn
  }
  // 生产模式：PyInstaller 打包的可执行文件放在 resources/backend/
  const ext = process.platform === 'win32' ? '.exe' : ''
  return path.join(process.resourcesPath, 'backend', 'backend', `backend${ext}`)
}

function startBackend() {
  if (isDev) {
    console.log('[dev] 请手动启动后端: cd .. && uvicorn main:app --port 8000')
    return
  }

  const backendPath = getBackendPath()
  console.log('[backend] 启动:', backendPath)

  backendProcess = spawn(backendPath, [], {
    cwd: path.join(process.resourcesPath, 'backend', 'backend'),
    env: { ...process.env, PORT: String(PORT) },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  backendProcess.stdout.on('data', (d) => console.log('[backend]', d.toString().trim()))
  backendProcess.stderr.on('data', (d) => console.error('[backend]', d.toString().trim()))

  backendProcess.on('exit', (code) => {
    console.warn('[backend] 进程退出，code:', code)
  })
}

function waitForBackend(retries = 180, onProgress = null) {
  const total = retries
  return new Promise((resolve, reject) => {
    let backendExited = false

    // Watch for backend process exit to fail fast
    if (backendProcess) {
      backendProcess.on('exit', (code) => {
        backendExited = true
      })
    }

    const attempt = (n) => {
      // If backend process already exited, don't keep retrying
      if (backendExited) {
        reject(new Error('后端进程已退出，请检查日志'))
        return
      }

      if (onProgress) {
        onProgress(total - n, total)
      }

      http.get(`http://localhost:${PORT}/api/health`, (res) => {
        if (res.statusCode < 500) resolve()
        else if (n > 0) setTimeout(() => attempt(n - 1), 1000)
        else reject(new Error('后端启动超时（180秒），请检查防火墙或端口占用'))
      }).on('error', () => {
        if (n > 0) setTimeout(() => attempt(n - 1), 1000)
        else reject(new Error('后端启动超时（180秒），请检查防火墙或端口占用'))
      })
    }
    attempt(retries)
  })
}

function createSplash() {
  splashWindow = new BrowserWindow({
    width: 360,
    height: 200,
    frame: false,
    transparent: true,
    resizable: false,
    alwaysOnTop: true,
    webPreferences: { contextIsolation: true },
  })

  const html = `
    <html>
    <head><meta charset="utf-8"><style>
      body { margin:0; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:rgba(17,23,35,0.95); color:#f3f7ff; display:flex; flex-direction:column; align-items:center; justify-content:center; height:100vh; -webkit-app-region:drag; border-radius:16px; }
      h1 { font-size:16px; font-weight:600; margin:0 0 8px; }
      p { font-size:12px; color:#6c7a92; margin:0 0 16px; }
      .bar { width:200px; height:4px; background:rgba(127,178,255,0.15); border-radius:2px; overflow:hidden; }
      .bar-inner { height:100%; background:linear-gradient(90deg,#7fb2ff,#8de3ff); border-radius:2px; transition:width 0.3s; }
    </style></head>
    <body>
      <h1>Account Manager</h1>
      <p id="msg">正在启动后端服务...</p>
      <div class="bar"><div class="bar-inner" id="progress" style="width:0%"></div></div>
    </body>
    </html>`

  splashWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(html))
}

function updateSplashProgress(current, total) {
  if (!splashWindow || splashWindow.isDestroyed()) return
  const pct = Math.min(Math.round((current / total) * 100), 99)
  splashWindow.webContents.executeJavaScript(
    `document.getElementById('progress').style.width='${pct}%';` +
    `document.getElementById('msg').textContent='正在启动后端服务... (${current}s)';`
  ).catch(() => {})
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.close()
    splashWindow = null
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    title: 'Account Manager',
    show: false,
    webPreferences: {
      contextIsolation: true,
    },
  })

  mainWindow.loadURL(`http://localhost:${PORT}`)
  mainWindow.once('ready-to-show', () => {
    closeSplash()
    mainWindow.show()
  })
  mainWindow.on('closed', () => { mainWindow = null })

  // 外部链接在系统浏览器中打开
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('http://') || url.startsWith('https://')) {
      shell.openExternal(url)
      return { action: 'deny' }
    }
    return { action: 'allow' }
  })
}

app.whenReady().then(async () => {
  createSplash()
  startBackend()

  try {
    await waitForBackend(180, updateSplashProgress)
  } catch (err) {
    closeSplash()
    dialog.showErrorBox('启动失败', err.message)
    app.quit()
    return
  }

  createWindow()

  // ── 自动更新（仅 Windows，macOS 未签名不支持） ──
  if (process.platform === 'win32' && !isDev) {
    autoUpdater.autoDownload = false
    autoUpdater.autoInstallOnAppQuit = true

    autoUpdater.on('update-available', (info) => {
      dialog.showMessageBox(mainWindow, {
        type: 'info',
        title: '发现新版本',
        message: `新版本 v${info.version} 可用，是否下载？`,
        buttons: ['下载更新', '稍后'],
        defaultId: 0,
      }).then(({ response }) => {
        if (response === 0) {
          autoUpdater.downloadUpdate()
        }
      })
    })

    autoUpdater.on('update-downloaded', () => {
      dialog.showMessageBox(mainWindow, {
        type: 'info',
        title: '更新就绪',
        message: '新版本已下载完成，重启应用即可安装。',
        buttons: ['立即重启', '稍后'],
        defaultId: 0,
      }).then(({ response }) => {
        if (response === 0) {
          autoUpdater.quitAndInstall()
        }
      })
    })

    autoUpdater.on('error', (err) => {
      console.error('[updater] 检查更新失败:', err.message)
    })

    // 启动后 10 秒检查更新
    setTimeout(() => autoUpdater.checkForUpdates(), 10000)
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('will-quit', () => {
  if (backendProcess) {
    // On Windows, child_process.kill() doesn't kill the process tree.
    // Use taskkill to ensure all child processes are terminated.
    if (process.platform === 'win32') {
      try {
        require('child_process').execSync(`taskkill /pid ${backendProcess.pid} /T /F`, { stdio: 'ignore' })
      } catch (_) {
        backendProcess.kill()
      }
    } else {
      backendProcess.kill()
    }
    backendProcess = null
  }
})
