import type { Job, SetSummary } from '../../../shared/api'
import { AlertIcon, BrickIcon, CheckIcon, FileIcon, PlusIcon } from '../components/Icons'
import { libraryUrl, plural } from '../engine'

function capitalise(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s
}

function JobCard({
  job,
  onCancel,
  onDismiss,
  onOpen
}: {
  job: Job
  onCancel: () => void
  onDismiss: () => void
  onOpen: (id: number) => void
}): React.JSX.Element {
  const busy = job.state === 'queued' || job.state === 'running'
  return (
    <article className={`card job-card ${job.state}`} aria-label={`Importing ${job.name}`}>
      <div className="card-cover placeholder">
        {job.state === 'failed' ? <AlertIcon width={28} height={28} /> : <FileIcon width={28} height={28} />}
      </div>
      <div className="card-body">
        <h3 className="card-title" title={job.path}>
          {job.name}
        </h3>
        {busy && (
          <>
            <p className="card-meta">
              {job.state === 'queued'
                ? 'Waiting for the import before it…'
                : `${capitalise(job.stage || 'starting')}… ${Math.round(job.fraction * 100)}%`}
            </p>
            <div className="progress" role="progressbar" aria-valuenow={Math.round(job.fraction * 100)}>
              <div style={{ width: `${Math.max(2, job.fraction * 100)}%` }} />
            </div>
            <div className="card-actions">
              <button className="button small" onClick={onCancel}>
                Cancel
              </button>
            </div>
          </>
        )}
        {job.state === 'failed' && (
          <>
            <p className="card-meta error-text">Couldn’t import this PDF. {job.error}</p>
            <div className="card-actions">
              <button className="button small" onClick={onDismiss}>
                Dismiss
              </button>
            </div>
          </>
        )}
        {job.state === 'exists' && (
          <>
            <p className="card-meta">This PDF is already in your library.</p>
            <div className="card-actions">
              {job.set_id !== null && (
                <button
                  className="button small"
                  onClick={() => {
                    onDismiss()
                    onOpen(job.set_id!)
                  }}
                >
                  Open it
                </button>
              )}
              <button className="button small" onClick={onDismiss}>
                Dismiss
              </button>
            </div>
          </>
        )}
      </div>
    </article>
  )
}

function SetCard({
  set,
  onOpen,
  onReview
}: {
  set: SetSummary
  onOpen: () => void
  onReview: () => void
}): React.JSX.Element {
  return (
    <article className="card set-card">
      <button className="card-open" onClick={onOpen} aria-label={`Open ${set.name}`}>
        <div className="card-cover">
          {set.cover ? <img src={libraryUrl(set.cover)} alt="" /> : <BrickIcon width={36} height={36} />}
        </div>
        <div className="card-body">
          <h3 className="card-title">{set.name}</h3>
          <p className="card-meta">
            {set.set_number && set.name !== `Set ${set.set_number}` ? `Set ${set.set_number} · ` : ''}
            {plural(set.pieces, 'piece')}
            {set.bags ? ` · ${plural(set.bags, 'bag')}` : ''}
          </p>
        </div>
      </button>
      <div className="card-status">
        {set.to_check ? (
          <button className="status warn" onClick={onReview}>
            <AlertIcon /> {plural(set.to_check, 'part')} to check
          </button>
        ) : (
          <span className="status ok">
            <CheckIcon /> All parts add up
          </span>
        )}
      </div>
    </article>
  )
}

export function Library({
  sets,
  jobs,
  onOpen,
  onReview,
  onImport,
  onCancel,
  onDismiss
}: {
  sets: SetSummary[] | null
  jobs: Job[]
  onOpen: (id: number) => void
  onReview: (id: number) => void
  onImport: () => void
  onCancel: (job: Job) => void
  onDismiss: (job: Job) => void
}): React.JSX.Element {
  if (sets === null) return <div className="screen" />

  if (!sets.length && !jobs.length) {
    return (
      <div className="screen empty">
        <BrickIcon className="empty-mark" width={56} height={56} />
        <h1>Your library is empty</h1>
        <p>
          Import a LEGO building instruction PDF you have downloaded. BrickWise reads it on this computer, works out
          which parts each step and bag uses, and keeps the result here. Nothing is uploaded.
        </p>
        <button className="button primary large" onClick={onImport}>
          <PlusIcon /> Import PDF
        </button>
        <p className="hint">or drop PDFs anywhere in this window</p>
      </div>
    )
  }

  return (
    <div className="screen">
      <div className="screen-head">
        <h1>Library</h1>
        <span className="muted">{plural(sets.length, 'set')}</span>
      </div>
      <div className="card-grid">
        {jobs.map((job) => (
          <JobCard
            key={`job-${job.id}`}
            job={job}
            onCancel={() => onCancel(job)}
            onDismiss={() => onDismiss(job)}
            onOpen={onOpen}
          />
        ))}
        {sets.map((s) => (
          <SetCard key={s.id} set={s} onOpen={() => onOpen(s.id)} onReview={() => onReview(s.id)} />
        ))}
      </div>
    </div>
  )
}
