import { existsSync } from 'node:fs'
import { join, resolve, sep } from 'node:path'
import { pathToFileURL } from 'node:url'

import { app, BrowserWindow, dialog, ipcMain, nativeTheme, net, protocol, shell } from 'electron'

import { METHODS, type EngineEvent } from '../shared/api'
import { Engine, type EngineCommand } from './engine'

// The user's library: a SQLite database and pictures cut from their own PDFs.
// Tests point it somewhere else with BRICKWISE_LIBRARY.
const libraryDir = resolve(process.env.BRICKWISE_LIBRARY ?? join(app.getPath('userData'), 'library'))

protocol.registerSchemesAsPrivileged([
  { scheme: 'brickwise', privileges: { standard: true, secure: true, supportFetchAPI: true } }
])

function engineCommand(): EngineCommand {
  const args = ['serve', '--library', libraryDir]
  if (app.isPackaged) {
    // Bundled by PyInstaller, see engine/packaging/build.py.
    const exe = process.platform === 'win32' ? 'brickwise-engine.exe' : 'brickwise-engine'
    return { command: join(process.resourcesPath, 'engine', exe), args }
  }
  // Development: run the engine from source, preferring its virtualenv.
  const engineDir = resolve(app.getAppPath(), '..', 'engine')
  const venv =
    process.platform === 'win32'
      ? join(engineDir, '.venv', 'Scripts', 'python.exe')
      : join(engineDir, '.venv', 'bin', 'python')
  const python =
    process.env.BRICKWISE_PYTHON ?? (existsSync(venv) ? venv : process.platform === 'win32' ? 'python' : 'python3')
  return { command: python, args: ['-m', 'brickwise', ...args], cwd: engineDir }
}

const engine = new Engine(engineCommand())
let window: BrowserWindow | null = null

function send(event: EngineEvent): void {
  window?.webContents.send('engine:event', event)
}

engine.on('event', send)
engine.on('stopped', (error: Error) => send({ event: 'engine-stopped', message: error.message }))

function createWindow(): void {
  const win = new BrowserWindow({
    width: 1240,
    height: 820,
    minWidth: 860,
    minHeight: 560,
    show: false,
    title: 'BrickWise',
    backgroundColor: nativeTheme.shouldUseDarkColors ? '#1c1b1a' : '#f7f6f3',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false
    }
  })
  window = win
  win.on('ready-to-show', () => win.show())
  win.on('closed', () => {
    if (window === win) window = null
  })
  // The window only ever shows the app itself; web links open in the browser.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) void shell.openExternal(url)
    return { action: 'deny' }
  })
  win.webContents.on('will-navigate', (event) => event.preventDefault())

  if (!app.isPackaged && process.env.ELECTRON_RENDERER_URL) {
    void win.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    void win.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

function inLibrary(file: string): boolean {
  return file.startsWith(libraryDir + sep)
}

app.whenReady().then(() => {
  protocol.handle('brickwise', async (request) => {
    const url = new URL(request.url)
    const file = resolve(libraryDir, decodeURIComponent(url.pathname).replace(/^\/+/, ''))
    if (url.host !== 'library' || !inLibrary(file) || !existsSync(file)) {
      return new Response('Not found', { status: 404 })
    }
    return net.fetch(pathToFileURL(file).toString())
  })

  ipcMain.handle('engine:call', async (_event, method: string, params: object) => {
    if (!(METHODS as string[]).includes(method)) return { error: `Unknown engine method ${method}` }
    try {
      return { result: await engine.call(method, params ?? {}) }
    } catch (err) {
      return { error: err instanceof Error ? err.message : String(err) }
    }
  })

  ipcMain.handle('dialog:pick-pdfs', async () => {
    const options: Electron.OpenDialogOptions = {
      title: 'Import building instructions',
      properties: ['openFile', 'multiSelections'],
      filters: [{ name: 'PDF', extensions: ['pdf'] }]
    }
    const result = window ? await dialog.showOpenDialog(window, options) : await dialog.showOpenDialog(options)
    return result.canceled ? [] : result.filePaths
  })

  ipcMain.handle('shell:show-in-folder', (_event, path: string) => {
    if (typeof path === 'string' && path.toLowerCase().endsWith('.pdf') && existsSync(path)) {
      shell.showItemInFolder(path)
    }
  })

  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('will-quit', () => engine.stop())
