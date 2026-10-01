import { useEffect, useId, useMemo, useState } from 'react'

import type { Bag, PictureGroup, Review, ReviewItem, StepRef } from '../../../shared/api'
import { AlertIcon, CheckIcon, CloseIcon } from '../components/Icons'
import { PageViewer, type PageTarget } from '../components/PageViewer'
import { call, libraryUrl, plural } from '../engine'

const USES_SHOWN = 6

function difference(item: ReviewItem): string {
  const d = item.steps - item.inventory
  if (item.inventory === 0) return 'not in the inventory'
  if (d > 0) return `${d} too many`
  return `${-d} missing`
}

function Thumb({ picture, label }: { picture: string | null; label: string }): React.JSX.Element {
  return <div className="thumb">{picture && <img src={libraryUrl(picture)} alt={label} />}</div>
}

function Uses({
  group,
  label,
  onShowPage
}: {
  group: PictureGroup
  label: string
  onShowPage: (t: PageTarget) => void
}): React.JSX.Element {
  const [all, setAll] = useState(false)
  const uses = all ? group.uses : group.uses.slice(0, USES_SHOWN)
  return (
    <div className="group-uses">
      <span className="muted">{label}</span>
      {uses.map((u) => (
        <button key={u.id} className="link" onClick={() => onShowPage({ page: u.page, box: u.box })}>
          {u.step !== null ? `step ${u.step}` : 'a step'} (p. {u.page}
          {u.count > 1 || u.factor > 1 ? `, ${u.count}x${u.factor > 1 ? ` × ${u.factor}` : ''}` : ''})
        </button>
      ))}
      {group.uses.length > USES_SHOWN && !all && (
        <button className="link" onClick={() => setAll(true)}>
          and {group.uses.length - USES_SHOWN} more
        </button>
      )}
    </div>
  )
}

function Group({
  group,
  parts,
  onShowPage,
  onReassign
}: {
  group: PictureGroup
  parts: Review['parts']
  onShowPage: (t: PageTarget) => void
  onReassign: (elementId: string) => void
}): React.JSX.Element {
  const [other, setOther] = useState('')
  const listId = useId()
  const valid = parts.some((p) => p.element_id === other.trim())

  return (
    <div className="group">
      <Thumb picture={group.picture} label="Step picture" />
      <div className="group-body">
        <Uses
          group={group}
          label={`${group.edited ? 'You matched this step picture to this part. ' : ''}${plural(group.pieces, 'piece')} in`}
          onShowPage={onShowPage}
        />
        <div className="candidates">
          <span className="muted">Is this a different part?</span>
          {group.candidates.map((c) => (
            <button
              key={c.element_id}
              className="candidate"
              onClick={() => onReassign(c.element_id)}
              title={`Use ${c.element_id} for this picture in every step`}
            >
              <Thumb picture={c.picture} label={`Part ${c.element_id}`} />
              <span className="candidate-id">{c.element_id}</span>
              <span className={`candidate-count ${c.steps < c.inventory ? 'short' : ''}`}>
                {c.steps < c.inventory
                  ? `${c.inventory - c.steps} missing`
                  : c.steps > c.inventory
                    ? `${c.steps - c.inventory} too many`
                    : 'adds up'}
              </span>
            </button>
          ))}
          <form
            className="other-part"
            onSubmit={(e) => {
              e.preventDefault()
              if (valid) onReassign(other.trim())
            }}
          >
            <input
              list={listId}
              placeholder="Other element ID"
              value={other}
              onChange={(e) => setOther(e.target.value)}
              aria-label="Other element ID"
            />
            <datalist id={listId}>
              {parts.map((p) => (
                <option key={p.element_id} value={p.element_id} />
              ))}
            </datalist>
            <button className="button small" disabled={!valid}>
              Use
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}

function PlaceControl({
  bags,
  steps,
  onPlace
}: {
  bags: Bag[]
  steps: StepRef[]
  onPlace: (where: { bag?: number; step_id?: number }) => void
}): React.JSX.Element {
  const [bag, setBag] = useState<number | ''>(bags[0]?.number ?? '')
  const [step, setStep] = useState<number | ''>('')
  const options = bags.length ? steps.filter((s) => s.bag === bag) : steps
  const canPlace = step !== '' || bag !== ''

  return (
    <div className="place">
      <span className="muted">Add a piece to</span>
      {bags.length > 0 && (
        <select
          value={bag}
          aria-label="Bag"
          onChange={(e) => {
            setBag(Number(e.target.value))
            setStep('')
          }}
        >
          {bags.map((b) => (
            <option key={b.number} value={b.number}>
              Bag {b.number}
            </option>
          ))}
        </select>
      )}
      <select
        value={step}
        aria-label="Step"
        onChange={(e) => setStep(e.target.value === '' ? '' : Number(e.target.value))}
      >
        <option value="">{bags.length ? 'Any step' : 'Choose a step'}</option>
        {options.map((s) => (
          <option key={s.id} value={s.id}>
            Step {s.number} (p. {s.page})
          </option>
        ))}
      </select>
      <button
        className="button small"
        disabled={!canPlace}
        onClick={() => onPlace(step !== '' ? { step_id: step } : { bag: bag as number })}
      >
        Place 1x
      </button>
    </div>
  )
}

function Item({
  item,
  review,
  setId,
  onChange,
  onShowPage,
  onError
}: {
  item: ReviewItem & { gone?: boolean }
  review: Review
  setId: number
  onChange: (r: Review) => void
  onShowPage: (t: PageTarget) => void
  onError: (err: unknown) => void
}): React.JSX.Element {
  const run = (p: Promise<Review>): void => {
    p.then(onChange).catch(onError)
  }
  const resolved = item.ok || item.gone
  const state = resolved ? 'ok' : item.accepted ? 'accepted' : 'open'

  return (
    <article className={`review-item ${state}`} aria-label={`Part ${item.element_id}`}>
      <div className="item-head">
        <Thumb picture={item.picture} label={`Part ${item.element_id}`} />
        <div className="item-title">
          <h3>{item.element_id}</h3>
          {resolved ? (
            <span className="status ok">
              <CheckIcon /> Adds up now
            </span>
          ) : (
            <span className="muted">
              Inventory {item.inventory} · steps {item.steps} ·{' '}
              <span className={item.accepted ? '' : 'warn-text'}>{difference(item)}</span>
              {item.page ? (
                <>
                  {' · '}
                  <button className="link" onClick={() => onShowPage({ page: item.page! })}>
                    inventory page
                  </button>
                </>
              ) : null}
            </span>
          )}
        </div>
        <span className="spacer" />
        {!resolved &&
          (item.accepted ? (
            <span className="accepted">
              Left as is
              <button
                className="button small"
                onClick={() => run(call('accept', { set_id: setId, element_id: item.element_id, accepted: false }))}
              >
                Undo
              </button>
            </span>
          ) : (
            <button
              className="button small"
              onClick={() => run(call('accept', { set_id: setId, element_id: item.element_id }))}
            >
              Leave as is
            </button>
          ))}
      </div>

      {!item.gone && !item.accepted && (
        <div className="item-body">
          {item.unplaced && !resolved && (
            <p className="explain">
              No step picture was matched to this part. It may be a look-alike of another part below, or one the book
              draws without a count, as many do for minifigures. Place each piece where it’s used; each counts as 1x.
            </p>
          )}
          {item.groups.map((g) => (
            <Group
              key={g.picture ?? 'none'}
              group={g}
              parts={review.parts}
              onShowPage={onShowPage}
              onReassign={(elementId) =>
                g.picture && run(call('reassign', { set_id: setId, picture: g.picture, element_id: elementId }))
              }
            />
          ))}
          {item.suspects.length > 0 && (
            <div className="suspects">
              <p className="muted">Step pictures matched to parts that came up over, which might be this one:</p>
              {item.suspects.map((g) => (
                <div className="group" key={g.picture ?? g.matched_to}>
                  <Thumb picture={g.picture} label="Step picture" />
                  <div className="group-body">
                    <Uses
                      group={g}
                      label={`${plural(g.pieces, 'piece')} matched to ${g.matched_to}, in`}
                      onShowPage={onShowPage}
                    />
                    <div>
                      <button
                        className="button small"
                        onClick={() =>
                          g.picture &&
                          run(call('reassign', { set_id: setId, picture: g.picture, element_id: item.element_id }))
                        }
                      >
                        It’s {item.element_id}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
          {item.placed.length > 0 && (
            <div className="placed">
              <span className="muted">Placed by you:</span>
              {item.placed.map((p) => (
                <span key={p.id} className="placed-chip">
                  {p.bag !== null ? `Bag ${p.bag}` : ''}
                  {p.bag !== null && p.step !== null ? ', ' : ''}
                  {p.step !== null ? `step ${p.step}` : ''}
                  {p.bag === null && p.step === null ? `page ${p.page}` : ''}
                  <button
                    className="icon-button tiny"
                    aria-label="Remove this piece"
                    onClick={() => run(call('unplace', { set_id: setId, callout_id: p.id }))}
                  >
                    <CloseIcon />
                  </button>
                </span>
              ))}
            </div>
          )}
          {item.steps < item.inventory && (review.bags.length > 0 || review.steps.length > 0) && (
            <PlaceControl
              bags={review.bags}
              steps={review.steps}
              onPlace={(where) => run(call('place', { set_id: setId, element_id: item.element_id, ...where }))}
            />
          )}
        </div>
      )}
    </article>
  )
}

export function ReviewScreen({
  setId,
  onDone,
  onError
}: {
  setId: number
  onDone: () => void
  onError: (err: unknown) => void
}): React.JSX.Element {
  const [review, setReview] = useState<Review | null>(null)
  // Parts seen earlier on this screen, so a fixed part stays visible (as fixed)
  // instead of vanishing from under the pointer.
  const [seen, setSeen] = useState<Map<string, ReviewItem>>(new Map())
  const [page, setPage] = useState<PageTarget | null>(null)

  const update = (r: Review): void => {
    setReview(r)
    setSeen((prev) => {
      const next = new Map(prev)
      for (const item of r.items) if (!next.has(item.element_id)) next.set(item.element_id, item)
      return next
    })
  }

  useEffect(() => {
    call('review', { set_id: setId }).then(update).catch(onError)
  }, [setId, onError])

  const items = useMemo(() => {
    if (!review) return []
    const current = new Map(review.items.map((i) => [i.element_id, i]))
    const all: (ReviewItem & { gone?: boolean })[] = [...seen.values()].map(
      (old) => current.get(old.element_id) ?? { ...old, gone: true }
    )
    const rank = (i: ReviewItem & { gone?: boolean }): number => (i.ok || i.gone ? 2 : i.accepted ? 1 : 0)
    return all.sort((a, b) => rank(a) - rank(b))
  }, [review, seen])

  if (!review) return <div className="screen" />

  const open = review.set.to_check
  return (
    <div className="screen review">
      <div className="screen-head">
        <div>
          <h1>Check parts</h1>
          <p className="muted">
            {review.set.name} · {review.set.reconciled} of {plural(review.set.parts, 'part')} add up
          </p>
        </div>
        <span className="spacer" />
        {open > 0 && (
          <button className="button" onClick={() => call('accept', { set_id: setId }).then(update).catch(onError)}>
            Leave the rest as is
          </button>
        )}
        <button className="button primary" onClick={onDone}>
          Done
        </button>
      </div>

      <p className="explain intro">
        BrickWise adds up the parts list of every step and compares the totals with the inventory at the back of the
        book. {open > 0 ? `${plural(open, 'part')} didn’t match.` : 'Everything matches now.'} Fix what you can; a part
        you leave as is keeps the counts the steps show.
      </p>

      {items.length === 0 && (
        <p className="all-good">
          <CheckIcon /> Every part adds up. Nothing to check.
        </p>
      )}
      {items.map((item) => (
        <Item
          key={item.element_id}
          item={item}
          review={review}
          setId={setId}
          onChange={update}
          onShowPage={setPage}
          onError={onError}
        />
      ))}
      {open > 0 && (
        <p className="muted footnote">
          <AlertIcon /> Parts left to check still show in the set with a warning mark.
        </p>
      )}
      {page && <PageViewer setId={setId} target={page} onClose={() => setPage(null)} />}
    </div>
  )
}
