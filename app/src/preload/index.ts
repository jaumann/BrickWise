import { contextBridge, ipcRenderer, webUtils } from 'electron'

import type { BrickWiseApi, EngineEvent } from '../shared/api'

const api: BrickWiseApi = {
  async call(method, params) {
    const reply = await ipcRenderer.invoke('engine:call', method, params ?? {})
    if (reply.error !== undefined) throw new Error(reply.error)
    return reply.result
  },
  pickPdfs: () => ipcRenderer.invoke('dialog:pick-pdfs'),
  pathForFile: (file) => webUtils.getPathForFile(file),
  showInFolder: (path) => ipcRenderer.invoke('shell:show-in-folder', path),
  onEvent(listener) {
    const handler = (_event: Electron.IpcRendererEvent, msg: EngineEvent): void => listener(msg)
    ipcRenderer.on('engine:event', handler)
    return () => ipcRenderer.removeListener('engine:event', handler)
  },
  platform: process.platform
}

contextBridge.exposeInMainWorld('brickwise', api)
