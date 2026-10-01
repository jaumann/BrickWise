// Shapes of what the engine sends back. They mirror engine/brickwise/library.py
// and engine/brickwise/server.py; keep the two in step.

export interface SetSummary {
  id: number
  set_number: string | null
  name: string
  pdf_path: string
  pdf_found: boolean
  page_count: number
  imported_at: string
  parts: number
  pieces: number
  bags: number
  reconciled: number
  to_check: number
  cover: string | null
}

export interface Bag {
  number: number
  page: number
}

export interface InventoryPart {
  element_id: string
  count: number
  page: number
  picture: string | null
  bags: [number, number][]
  no_bag: number
  status: 'ok' | 'check' | 'accepted'
}

export interface SetDetail extends SetSummary {
  bag_list: Bag[]
  inventory: InventoryPart[]
}

export interface Candidate {
  element_id: string
  picture: string | null
  inventory: number
  steps: number
}

export interface Use {
  id: number
  page: number
  step: number | null
  count: number
  factor: number
  box: [number, number, number, number] | null
}

export interface PictureGroup {
  picture: string | null
  confidence: number
  edited: boolean
  pieces: number
  uses: Use[]
  candidates: Candidate[]
}

export interface Placement {
  id: number
  page: number
  step: number | null
  bag: number | null
}

export interface ReviewItem {
  element_id: string
  inventory: number
  steps: number
  unplaced: boolean
  ok: boolean
  accepted: boolean
  picture: string | null
  page: number | null
  groups: PictureGroup[]
  placed: Placement[]
  /** Step pictures matched to an over-counted part that list this part as a close match. */
  suspects: (PictureGroup & { matched_to: string })[]
}

export interface StepRef {
  id: number
  number: number
  page: number
  bag: number | null
}

export interface Review {
  set: SetSummary
  items: ReviewItem[]
  bags: Bag[]
  steps: StepRef[]
  parts: { element_id: string; picture: string | null; inventory: number }[]
}

export interface Job {
  id: number
  path: string
  name: string
  state: 'queued' | 'running' | 'done' | 'exists' | 'failed' | 'cancelled'
  stage: string
  fraction: number
  set_id: number | null
  error: string | null
}

export interface PageImage {
  path: string
  page: number
  page_count: number
  width: number
  height: number
}

export type EngineEvent = { event: 'job'; job: Job } | { event: 'engine-stopped'; message: string }

// Engine methods the window may call, with their parameters and results.
export interface Methods {
  version: [Record<string, never>, { engine: string; library: string }]
  list_sets: [Record<string, never>, SetSummary[]]
  get_set: [{ set_id: number }, SetDetail]
  import_pdf: [{ path: string }, Job]
  jobs: [Record<string, never>, Job[]]
  cancel: [{ job_id: number }, null]
  dismiss: [{ job_id: number }, null]
  review: [{ set_id: number }, Review]
  reassign: [{ set_id: number; picture: string; element_id: string }, Review]
  place: [{ set_id: number; element_id: string; step_id?: number; bag?: number }, Review]
  unplace: [{ set_id: number; callout_id: number }, Review]
  accept: [{ set_id: number; element_id?: string; accepted?: boolean }, Review]
  rename: [{ set_id: number; name: string }, SetDetail]
  delete: [{ set_id: number }, null]
  page_image: [{ set_id: number; page: number }, PageImage]
}

export type Method = keyof Methods

export const METHODS: Method[] = [
  'version',
  'list_sets',
  'get_set',
  'import_pdf',
  'jobs',
  'cancel',
  'dismiss',
  'review',
  'reassign',
  'place',
  'unplace',
  'accept',
  'rename',
  'delete',
  'page_image'
]

// What the preload script exposes to the window as `window.brickwise`.
export interface BrickWiseApi {
  call<M extends Method>(method: M, params?: Methods[M][0]): Promise<Methods[M][1]>
  pickPdfs(): Promise<string[]>
  pathForFile(file: File): string
  showInFolder(path: string): Promise<void>
  onEvent(listener: (event: EngineEvent) => void): () => void
  platform: string
}

// Pictures and pages are files in the library folder, served to the window
// through this URL scheme.
export const LIBRARY_URL = 'brickwise://library/'
