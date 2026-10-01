import { execFileSync } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

import { _electron as electron, expect, test, type ElectronApplication, type Page } from '@playwright/test'

// These tests drive the real app and engine with small synthetic books drawn by
// engine/tests/make_book.py, so they need no LEGO PDFs. Set BRICKWISE_APP to a
// packaged app's executable to test that instead of the development build.

const appDir = resolve(__dirname, '..')
const engineDir = resolve(appDir, '..', 'engine')
const python = process.env.BRICKWISE_PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3')

let workDir: string

test.beforeEach(() => {
  workDir = mkdtempSync(join(tmpdir(), 'brickwise-e2e-'))
})

test.afterEach(() => {
  rmSync(workDir, { recursive: true, force: true })
})

function makeBook(name: string, variant = 'default'): string {
  const path = join(workDir, name)
  execFileSync(python, [join('tests', 'make_book.py'), path, variant], { cwd: engineDir })
  return path
}

async function launch(): Promise<{ app: ElectronApplication; page: Page }> {
  const packaged = process.env.BRICKWISE_APP
  const app = await electron.launch({
    ...(packaged ? { executablePath: packaged, args: [] } : { args: [appDir] }),
    env: { ...process.env, BRICKWISE_LIBRARY: join(workDir, 'library') }
  })
  const page = await app.firstWindow()
  page.on('pageerror', (err) => console.error(err))
  return { app, page }
}

async function importPdfs(app: ElectronApplication, page: Page, paths: string[]): Promise<void> {
  // Stand in for the native file dialog.
  await app.evaluate(({ dialog }, files) => {
    dialog.showOpenDialog = (async () => ({ canceled: false, filePaths: files })) as typeof dialog.showOpenDialog
  }, paths)
  await page.getByRole('button', { name: 'Import PDF' }).first().click()
}

test('imports a book and lists its parts by bag', async () => {
  const book = makeBook('castle.pdf')
  const { app, page } = await launch()
  await expect(page.getByRole('heading', { name: 'Your library is empty' })).toBeVisible()

  await importPdfs(app, page, [book])
  const card = page.getByRole('button', { name: 'Open Set 99901' })
  await expect(card).toBeVisible({ timeout: 60_000 })
  await expect(page.getByText('All parts add up')).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('library.png') })

  await card.click()
  await expect(page.getByRole('heading', { name: 'Set 99901' })).toBeVisible()
  await expect(page.locator('.tile')).toHaveCount(5)
  await page.getByRole('tab', { name: /Bag 2/ }).click()
  await expect(page.locator('.tile')).toHaveCount(3)
  await expect(page.locator('.tile[data-element="302301"] .tile-qty')).toHaveText('3x')
  await page.screenshot({ path: test.info().outputPath('set.png') })

  await page.getByRole('button', { name: 'Rename' }).click()
  await page.getByLabel('Set name').fill('Test castle')
  await page.getByLabel('Set name').press('Enter')
  await expect(page.getByRole('heading', { name: 'Test castle' })).toBeVisible()

  // The same PDF again is recognised rather than imported twice.
  await importPdfs(app, page, [book])
  await expect(page.getByText('This PDF is already in your library.')).toBeVisible({ timeout: 60_000 })
  await page.getByRole('button', { name: 'Open it' }).click()
  await expect(page.getByRole('heading', { name: 'Test castle' })).toBeVisible()
  await app.close()
})

test('review lets you place a part no step counts', async () => {
  const book = makeBook('minifig.pdf', 'unplaced')
  const { app, page } = await launch()
  await importPdfs(app, page, [book])
  await page.getByRole('button', { name: '1 part to check' }).click({ timeout: 60_000 })

  await expect(page.getByRole('heading', { name: 'Check parts' })).toBeVisible()
  const item = page.getByRole('article', { name: 'Part 4211415' })
  await expect(item.getByText('No step picture was matched to this part')).toBeVisible()

  await item.getByRole('button', { name: 'inventory page' }).click()
  const viewer = page.getByRole('dialog')
  await expect(viewer.getByRole('img')).toBeVisible()
  await expect(viewer.getByText('Page 9 of 9')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(viewer).toBeHidden()

  await item.getByLabel('Bag').selectOption('2')
  await item.getByRole('button', { name: 'Place 1x' }).click()
  await expect(item.getByText('Adds up now')).toBeVisible()
  await expect(item.getByText('Bag 2')).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('review.png') })

  await page.getByRole('button', { name: 'Done' }).click()
  await expect(page.getByText('All parts add up')).toBeVisible()
  await page.getByRole('tab', { name: /Bag 2/ }).click()
  await expect(page.locator('.tile[data-element="4211415"] .tile-qty')).toHaveText('1x')
  await app.close()
})

test('a PDF that is not an instruction book is reported', async () => {
  const notABook = makeBook('flyer.pdf', 'empty')
  const { app, page } = await launch()
  await importPdfs(app, page, [notABook])
  await expect(page.getByText('No parts inventory found')).toBeVisible({ timeout: 60_000 })
  await page.getByRole('button', { name: 'Dismiss' }).click()
  await expect(page.getByRole('heading', { name: 'Your library is empty' })).toBeVisible()
  await app.close()
})
