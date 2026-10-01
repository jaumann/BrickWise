import { useCallback, useEffect, useRef, useState } from 'react'

import type { Job, SetSummary } from '../../shared/api'
import { BrickIcon, ChevronRightIcon, CloseIcon, PlusIcon } from './components/Icons'
import { call } from './engine'
import { Library } from './screens/Library'
import { ReviewScreen } from './screens/Review'
import { SetView } from './screens/SetView'

export type View = { name: 'library' } | { name: 'set'; id: number } | { name: 'review'; id: number }

export default function App(): React.JSX.Element {
  const [view, setView] = useState<View>({ name: 'library' })
  const [sets, setSets] = useState<SetSummary[] | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const dragDepth = useRef(0)

  const report = useCallback((err: unknown) => {
    setError(err instanceof Error ? err.message : String(err))
  }, [])

  const refresh = useCallback(async () => {
    try {
      setSets(await call('list_sets'))
    } catch (err) {
      report(err)
    }
  }, [report])

  const upsertJob = useCallback((job: Job) => {
    setJobs((list) =>
      list.some((j) => j.id === job.id) ? list.map((j) => (j.id === job.id ? job : j)) : [...list, job]
    )
  }, [])

  const dismiss = useCallback(
    (job: Job) => {
      setJobs((list) => list.filter((j) => j.id !== job.id))
      call('dismiss', { job_id: job.id }).catch(report)
    },
    [report]
  )

  useEffect(() => {
    void refresh()
    call('jobs')
      .then((list) => setJobs(list.filter((j) => j.state !== 'done' && j.state !== 'cancelled')))
      .catch(report)
    return window.brickwise.onEvent((msg) => {
      if (msg.event === 'engine-stopped') {
        report(msg.message)
        return
      }
      const { job } = msg
      if (job.state === 'done' || job.state === 'cancelled') {
        // The new set shows up in the library in place of its progress card.
        dismiss(job)
        if (job.state === 'done') void refresh()
      } else {
        upsertJob(job)
      }
    })
  }, [refresh, report, upsertJob, dismiss])

  const importPaths = useCallback(
    async (paths: string[]) => {
      setView({ name: 'library' })
      for (const path of paths) {
        try {
          upsertJob(await call('import_pdf', { path }))
        } catch (err) {
          report(err)
        }
      }
    },
    [report, upsertJob]
  )

  const pickAndImport = useCallback(async () => {
    const paths = await window.brickwise.pickPdfs()
    if (paths.length) await importPaths(paths)
  }, [importPaths])

  // Dropping PDFs anywhere on the window imports them.
  useEffect(() => {
    const hasFiles = (e: DragEvent): boolean => !!e.dataTransfer && Array.from(e.dataTransfer.types).includes('Files')
    const enter = (e: DragEvent): void => {
      if (!hasFiles(e)) return
      e.preventDefault()
      dragDepth.current += 1
      setDragging(true)
    }
    const over = (e: DragEvent): void => {
      if (hasFiles(e)) e.preventDefault()
    }
    const leave = (e: DragEvent): void => {
      if (!hasFiles(e)) return
      dragDepth.current = Math.max(0, dragDepth.current - 1)
      if (dragDepth.current === 0) setDragging(false)
    }
    const drop = (e: DragEvent): void => {
      e.preventDefault()
      dragDepth.current = 0
      setDragging(false)
      const files = Array.from(e.dataTransfer?.files ?? []).filter((f) => f.name.toLowerCase().endsWith('.pdf'))
      if (files.length) void importPaths(files.map((f) => window.brickwise.pathForFile(f)))
      else if (e.dataTransfer?.files.length) report('Only PDF files can be imported.')
    }
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragover', over)
    window.addEventListener('dragleave', leave)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', enter)
      window.removeEventListener('dragover', over)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('drop', drop)
    }
  }, [importPaths, report])

  const current = view.name !== 'library' ? sets?.find((s) => s.id === view.id) : undefined
  const goLibrary = (): void => {
    setView({ name: 'library' })
    void refresh()
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <BrickIcon className="brand-mark" />
          <span>BrickWise</span>
        </div>
        <nav className="crumbs" aria-label="Location">
          {view.name === 'library' ? (
            <span className="crumb current">Library</span>
          ) : (
            <>
              <button className="crumb" onClick={goLibrary}>
                Library
              </button>
              <ChevronRightIcon className="crumb-sep" />
              {view.name === 'review' ? (
                <>
                  <button className="crumb" onClick={() => setView({ name: 'set', id: view.id })}>
                    {current?.name ?? 'Set'}
                  </button>
                  <ChevronRightIcon className="crumb-sep" />
                  <span className="crumb current">Check parts</span>
                </>
              ) : (
                <span className="crumb current">{current?.name ?? 'Set'}</span>
              )}
            </>
          )}
        </nav>
        <span className="spacer" />
        <button className="button primary" onClick={() => void pickAndImport()}>
          <PlusIcon /> Import PDF
        </button>
      </header>

      <main className="content">
        {view.name === 'library' && (
          <Library
            sets={sets}
            jobs={jobs}
            onOpen={(id) => setView({ name: 'set', id })}
            onReview={(id) => setView({ name: 'review', id })}
            onImport={() => void pickAndImport()}
            onCancel={(job) => call('cancel', { job_id: job.id }).catch(report)}
            onDismiss={dismiss}
          />
        )}
        {view.name === 'set' && (
          <SetView
            key={view.id}
            setId={view.id}
            onReview={() => setView({ name: 'review', id: view.id })}
            onChanged={refresh}
            onRemoved={goLibrary}
            onError={report}
          />
        )}
        {view.name === 'review' && (
          <ReviewScreen
            key={view.id}
            setId={view.id}
            onDone={() => {
              setView({ name: 'set', id: view.id })
              void refresh()
            }}
            onError={report}
          />
        )}
      </main>

      {error && (
        <div className="toast" role="alert">
          <pre>{error}</pre>
          <button className="icon-button" onClick={() => setError(null)} aria-label="Dismiss">
            <CloseIcon />
          </button>
        </div>
      )}
      {dragging && (
        <div className="drop-overlay">
          <div>Drop PDFs to import them</div>
        </div>
      )}
    </div>
  )
}
