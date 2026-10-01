import { useEffect, useState } from 'react'

import type { PageImage } from '../../../shared/api'
import { call, libraryUrl } from '../engine'
import { ChevronLeftIcon, ChevronRightIcon, CloseIcon } from './Icons'

export interface PageTarget {
  page: number
  /** Area to outline, in PDF points from the top left of the page. */
  box?: [number, number, number, number] | null
}

/** One page of the instruction book, with an optional outline around a part picture. */
export function PageViewer({
  setId,
  target,
  onClose
}: {
  setId: number
  target: PageTarget
  onClose: () => void
}): React.JSX.Element {
  const [page, setPage] = useState(target.page)
  const [image, setImage] = useState<PageImage | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    setError(null)
    call('page_image', { set_id: setId, page })
      .then((img) => live && setImage(img))
      .catch((err: Error) => live && setError(err.message))
    return () => {
      live = false
    }
  }, [setId, page])

  const count = image?.page_count ?? 0
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft') setPage((p) => Math.max(1, p - 1))
      if (e.key === 'ArrowRight' && count) setPage((p) => Math.min(count, p + 1))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [count, onClose])

  const box = page === target.page ? target.box : null
  const shown = image && image.page === page ? image : null

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal page-viewer" role="dialog" aria-label={`Page ${page}`} onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <button
            className="icon-button"
            onClick={() => setPage(page - 1)}
            disabled={page <= 1}
            aria-label="Previous page"
          >
            <ChevronLeftIcon />
          </button>
          <span className="page-number">
            Page {page}
            {count ? ` of ${count}` : ''}
          </span>
          <button
            className="icon-button"
            onClick={() => setPage(page + 1)}
            disabled={!count || page >= count}
            aria-label="Next page"
          >
            <ChevronRightIcon />
          </button>
          <span className="spacer" />
          <button className="icon-button" onClick={onClose} aria-label="Close">
            <CloseIcon />
          </button>
        </div>
        <div className="page-body">
          {error ? (
            <p className="page-error">{error}</p>
          ) : shown ? (
            <div className="page-frame">
              <img src={libraryUrl(shown.path)} alt={`Page ${page} of the instructions`} />
              {box && (
                <div
                  className="page-highlight"
                  style={{
                    left: `${(box[0] / shown.width) * 100}%`,
                    top: `${(box[1] / shown.height) * 100}%`,
                    width: `${((box[2] - box[0]) / shown.width) * 100}%`,
                    height: `${((box[3] - box[1]) / shown.height) * 100}%`
                  }}
                />
              )}
            </div>
          ) : (
            <p className="page-loading">Loading page…</p>
          )}
        </div>
      </div>
    </div>
  )
}
