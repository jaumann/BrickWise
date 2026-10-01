import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { EventEmitter } from 'node:events'
import { createInterface } from 'node:readline'

export interface EngineCommand {
  command: string
  args: string[]
  cwd?: string
}

interface Pending {
  resolve: (value: unknown) => void
  reject: (error: Error) => void
}

/**
 * The Python engine, running as a child process that answers one JSON request
 * per line (see engine/brickwise/server.py). It starts on the first call and
 * starts again on the next call if it ever stops.
 */
export class Engine extends EventEmitter {
  private proc: ChildProcessWithoutNullStreams | null = null
  private nextId = 1
  private pending = new Map<number, Pending>()
  private stderr: string[] = []

  constructor(private readonly cmd: EngineCommand) {
    super()
  }

  call(method: string, params: object = {}): Promise<unknown> {
    const proc = this.proc ?? this.start()
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      proc.stdin.write(JSON.stringify({ id, method, params }) + '\n')
    })
  }

  stop(): void {
    const proc = this.proc
    if (!proc) return
    this.proc = null
    proc.stdin.end()
    const timer = setTimeout(() => proc.kill(), 3000)
    proc.once('exit', () => clearTimeout(timer))
  }

  private start(): ChildProcessWithoutNullStreams {
    const { command, args, cwd } = this.cmd
    const proc = spawn(command, args, {
      cwd,
      env: { ...process.env, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
      windowsHide: true
    })
    this.proc = proc
    this.stderr = []

    createInterface({ input: proc.stdout }).on('line', (line) => this.onLine(line))
    createInterface({ input: proc.stderr }).on('line', (line) => {
      console.error(`[engine] ${line}`)
      this.stderr.push(line)
      if (this.stderr.length > 40) this.stderr.shift()
    })

    const stopped = (reason: string): void => {
      if (this.proc === proc) this.proc = null
      const detail = this.stderr.slice(-8).join('\n')
      const error = new Error(detail ? `${reason}\n${detail}` : reason)
      for (const p of this.pending.values()) p.reject(error)
      this.pending.clear()
      this.emit('stopped', error)
    }
    proc.on('error', (err) => stopped(`Could not start the BrickWise engine (${command}): ${err.message}`))
    proc.on('exit', (code, signal) => {
      if (code !== 0 || this.pending.size > 0) {
        stopped(`The BrickWise engine stopped (${signal ?? `exit code ${code}`}).`)
      }
    })
    return proc
  }

  private onLine(line: string): void {
    let msg: { id?: number; result?: unknown; error?: { message: string }; event?: string }
    try {
      msg = JSON.parse(line)
    } catch {
      console.error(`[engine] not JSON: ${line}`)
      return
    }
    if (msg.event) {
      this.emit('event', msg)
      return
    }
    const p = msg.id !== undefined ? this.pending.get(msg.id) : undefined
    if (!p) return
    this.pending.delete(msg.id!)
    if (msg.error) p.reject(new Error(msg.error.message))
    else p.resolve(msg.result ?? null)
  }
}
