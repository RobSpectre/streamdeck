import { describe, expect, mock, test, tier } from 'claude-code/testing'

tier('user')

const ID = '0f8fad5b-d9cb-469f-a165-70867728950e'
const MEASURE = {
  context: { tokens: 50000, window: 200000, percent: 25 },
  rateLimits: [{ kind: 'five_hour', percentUsed: 12.5, resetsAt: '2026-09-28T01:00:00Z' }],
  changed: ['context', 'rateLimits'] as const,
}

describe('register', () => {
  test('a measurement is written for the deck and passed on unchanged', async ($, on) => {
    const written: { path: string; text: string }[] = []
    mock.env(on, { HOME: '/home/person' })
    mock.clock(on)
    on('session.id', () => ({ value: ID }))
    on('session.model', () => ({ value: 'claude-opus-5-5' }))
    on('fs.write', ($, e) => (written.push(e), { value: undefined }))
    on('session.measure', ($, e) => ({ changed: e.changed }))

    const result = await $.session.measure({ ...MEASURE, changed: [...MEASURE.changed] })

    expect(result.changed).toEqual(['context', 'rateLimits'])
    expect(written.map(w => w.path)).toEqual([`/home/person/.cache/opendeck-agents/claude-measure/${ID}.json`])
    const figures = JSON.parse(written[0].text)
    expect(figures.context).toEqual(MEASURE.context)
    expect(figures.rateLimits).toEqual(MEASURE.rateLimits)
    expect(figures.session).toBe(ID)
    expect(figures.model).toBe('claude-opus-5-5')
  })

  test('an odd session id or a failed write changes nothing', async ($, on) => {
    mock.env(on, { HOME: '/home/person' })
    mock.clock(on)
    on('session.id', () => ({ value: '../../escape' }))
    on('session.model', () => ({ value: 'claude-opus-5-5' }))
    on('fs.write', () => { throw new Error('must not write') })
    on('session.measure', ($, e) => ({ changed: e.changed }))

    const result = await $.session.measure({ ...MEASURE, changed: ['context'] })

    expect(result.changed).toEqual(['context'])
  })
})
