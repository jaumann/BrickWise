import { LIBRARY_URL, type Method, type Methods } from '../../shared/api'

export function call<M extends Method>(method: M, params?: Methods[M][0]): Promise<Methods[M][1]> {
  return window.brickwise.call(method, params)
}

/** URL of a file in the library folder, as the engine names it (e.g. "sets/1/cover.png"). */
export function libraryUrl(path: string | null | undefined): string | undefined {
  return path ? LIBRARY_URL + path.split('/').map(encodeURIComponent).join('/') : undefined
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`
}
