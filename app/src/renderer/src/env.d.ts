/// <reference types="vite/client" />

import type { BrickWiseApi } from '../../shared/api'

declare global {
  interface Window {
    brickwise: BrickWiseApi
  }
}
