import type { On } from 'claude-code'

/**
 * A session id is a UUID; nothing else may become a file name.
 */
const SESSION = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

/**
 * Hands Claude's own measurement to the OpenDeck bridge: the context window
 * and rate-limit windows the status line shows, which a session without one
 * (the desktop app's) has no other way to publish. Observes only: the figures
 * pass on unchanged, and a failed write never disturbs the session.
 *
 * @param on the engine's registrar
 */
export function register(on: On): void {
  on('session.measure', async ($, e, next) => {
    try {
      const [id, home, now, model] = await Promise.all([
        $.session.id(), $.env.get('HOME'), $.clock.now(), $.session.model(),
      ])
      if (home && SESSION.test(id)) {
        await $.fs.write(
          `${home}/.cache/opendeck-agents/claude-measure/${id}.json`,
          JSON.stringify({ session: id, measured: now / 1000, model, context: e.context, rateLimits: e.rateLimits }),
        )
      }
    } catch {
      // The deck's figures are optional; the session is not.
    }
    return next(e)
  })
}
