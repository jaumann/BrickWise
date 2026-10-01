import { useEffect, useMemo, useState } from 'react'

import type { InventoryPart, SetDetail } from '../../../shared/api'
import { AlertIcon, CheckIcon, FolderIcon, PencilIcon, SearchIcon, TrashIcon } from '../components/Icons'
import { call, libraryUrl, plural } from '../engine'

type Filter = 'all' | 'none' | number

function quantity(part: InventoryPart, filter: Filter): number {
  if (filter === 'all') return part.count
  if (filter === 'none') return part.no_bag
  return part.bags.find(([bag]) => bag === filter)?.[1] ?? 0
}

function PartTile({ part, qty }: { part: InventoryPart; qty: number }): React.JSX.Element {
  const title =
    part.status === 'check'
      ? "The steps don't add up to the inventory count for this part"
      : `Inventory page ${part.page}`
  return (
    <div className={`tile ${part.status}`} title={title} data-element={part.element_id}>
      <div className="tile-picture">
        {part.picture ? <img src={libraryUrl(part.picture)} alt={`Part ${part.element_id}`} /> : null}
      </div>
      <div className="tile-qty">{qty}x</div>
      <div className="tile-id">{part.element_id}</div>
      {part.status === 'check' && <AlertIcon className="tile-flag" />}
    </div>
  )
}

function NameEditor({ set, onSaved }: { set: SetDetail; onSaved: (s: SetDetail) => void }): React.JSX.Element {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(set.name)

  const save = async (): Promise<void> => {
    setEditing(false)
    if (name.trim() && name.trim() !== set.name) onSaved(await call('rename', { set_id: set.id, name }))
    else setName(set.name)
  }

  if (editing) {
    return (
      <input
        className="name-input"
        value={name}
        autoFocus
        aria-label="Set name"
        onChange={(e) => setName(e.target.value)}
        onBlur={() => void save()}
        onKeyDown={(e) => {
          if (e.key === 'Enter') void save()
          if (e.key === 'Escape') {
            setName(set.name)
            setEditing(false)
          }
        }}
      />
    )
  }
  return (
    <h1 className="set-name">
      {set.name}
      <button className="icon-button subtle" onClick={() => setEditing(true)} aria-label="Rename">
        <PencilIcon />
      </button>
    </h1>
  )
}

export function SetView({
  setId,
  onReview,
  onChanged,
  onRemoved,
  onError
}: {
  setId: number
  onReview: () => void
  onChanged: () => void
  onRemoved: () => void
  onError: (err: unknown) => void
}): React.JSX.Element {
  const [set, setSet] = useState<SetDetail | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [confirmRemove, setConfirmRemove] = useState(false)

  useEffect(() => {
    call('get_set', { set_id: setId }).then(setSet).catch(onError)
  }, [setId, onError])

  const shown = useMemo(() => {
    if (!set) return []
    const q = query.trim()
    return set.inventory
      .map((part) => ({ part, qty: quantity(part, filter) }))
      .filter(({ part, qty }) => qty > 0 && (!q || part.element_id.includes(q)))
  }, [set, filter, query])

  if (!set) return <div className="screen" />

  const noBag = set.inventory.reduce((n, p) => n + p.no_bag, 0)
  const bagPieces = (bag: number): number =>
    set.inventory.reduce((n, p) => n + (p.bags.find(([b]) => b === bag)?.[1] ?? 0), 0)

  const remove = async (): Promise<void> => {
    try {
      await call('delete', { set_id: set.id })
      onRemoved()
    } catch (err) {
      onError(err)
    }
  }

  return (
    <div className="screen">
      <div className="set-head">
        <div className="set-cover">{set.cover && <img src={libraryUrl(set.cover)} alt="" />}</div>
        <div className="set-info">
          <NameEditor
            set={set}
            onSaved={(s) => {
              setSet(s)
              onChanged()
            }}
          />
          <p className="muted">
            {set.set_number && set.name !== `Set ${set.set_number}` ? `Set ${set.set_number} · ` : ''}
            {plural(set.page_count, 'page')} · {plural(set.parts, 'part')} · {plural(set.pieces, 'piece')}
            {set.bags ? ` · ${plural(set.bags, 'bag')}` : ''}
          </p>
          <div className="set-status">
            {set.to_check ? (
              <>
                <span className="status warn">
                  <AlertIcon /> {plural(set.to_check, 'part')} to check
                </span>
                <button className="button small primary" onClick={onReview}>
                  Check parts
                </button>
              </>
            ) : (
              <>
                <span className="status ok">
                  <CheckIcon /> All parts add up
                </span>
                {set.reconciled < set.parts && (
                  <button className="button small" onClick={onReview}>
                    Review changes
                  </button>
                )}
              </>
            )}
          </div>
          {!set.pdf_found && (
            <p className="note">
              The PDF is no longer at {set.pdf_path}. Page previews need it there; everything else works without it.
            </p>
          )}
        </div>
        <div className="set-actions">
          {set.pdf_found && (
            <button className="button small" onClick={() => void window.brickwise.showInFolder(set.pdf_path)}>
              <FolderIcon /> Show PDF
            </button>
          )}
          {confirmRemove ? (
            <span className="confirm">
              Remove from library?
              <button className="button small danger" onClick={() => void remove()}>
                Remove
              </button>
              <button className="button small" onClick={() => setConfirmRemove(false)}>
                Keep
              </button>
            </span>
          ) : (
            <button className="button small" onClick={() => setConfirmRemove(true)}>
              <TrashIcon /> Remove
            </button>
          )}
        </div>
      </div>

      <div className="filters">
        <div className="chips" role="tablist" aria-label="Show parts for">
          <button role="tab" aria-selected={filter === 'all'} className="chip" onClick={() => setFilter('all')}>
            All <span className="chip-count">{set.pieces.toLocaleString()}</span>
          </button>
          {set.bag_list.map((b) => (
            <button
              key={b.number}
              role="tab"
              aria-selected={filter === b.number}
              className="chip"
              onClick={() => setFilter(b.number)}
            >
              Bag {b.number} <span className="chip-count">{bagPieces(b.number).toLocaleString()}</span>
            </button>
          ))}
          {set.bag_list.length > 0 && noBag > 0 && (
            <button role="tab" aria-selected={filter === 'none'} className="chip" onClick={() => setFilter('none')}>
              Not in a bag <span className="chip-count">{noBag.toLocaleString()}</span>
            </button>
          )}
        </div>
        <label className="search">
          <SearchIcon />
          <input
            placeholder="Element ID"
            value={query}
            inputMode="numeric"
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Find a part by element ID"
          />
        </label>
      </div>

      <p className="muted grid-summary">
        {plural(shown.length, 'part')},{' '}
        {plural(
          shown.reduce((n, s) => n + s.qty, 0),
          'piece'
        )}
        {filter === 'none' ? ' that no bag accounts for' : ''}
      </p>
      <div className="tile-grid">
        {shown.map(({ part, qty }) => (
          <PartTile key={part.element_id} part={part} qty={qty} />
        ))}
      </div>
    </div>
  )
}
