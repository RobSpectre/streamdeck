"""Per-capsule visibility in OBS browser-source CSS; preserve all other settings.

Selectors match livestream_chyrons' AgentBanner/MetricTile data attributes.
The managed rule is the visibility preference, independent of scene visibility.
"""
import re

CAPSULES = ('model', 'spark', 'speed', 'context', 'session', 'month')
AGENTS = ('codex', 'claude', 'hermes')
WEIGHTS = (2, 2.45, 1.2, 1.25, 1.45, 1.36)


def compact_css(css, agent):
    """Keep the original flex widths and remove hidden widths plus their gaps.

    Dimensions mirror AgentBanner/MetricTile: .22rem gap, .18rem capsule
    padding, theme-defined card padding/borders, and ROW_WEIGHTS. Container
    units refer to the full-width parent, never the shrinking card.
    """
    start, end = f'/* opendeck-width:{agent} */', f'/* /opendeck-width:{agent} */'
    pattern = re.escape(start) + r'.*?' + re.escape(end) + r'\n?'
    if css.count(start) != css.count(end) or css.count(start) > 1:
        raise ValueError('Modified capsule width rule')
    css = re.sub(pattern, '', css, flags=re.S)
    hidden = [key for key in CAPSULES if rule(agent, key) in css]
    if not hidden:
        return css
    card = f'[data-agent="{agent}"]'
    declarations = [
        f':has(> {card}) {{ container-type: inline-size; }}',
        f'{card} {{ --od-edge: calc(2 * var(--card-pad) + 2 * round(down, var(--nb-border-width), 1px)); '
        '--od-tile-edge: calc(.36rem + 2 * round(down, var(--nb-border-chip-width), 1px)); '
        '--od-space: calc(100cqw - var(--od-edge) - 1.1rem - 6 * var(--od-tile-edge)); }',
    ]
    for key, weight in zip(CAPSULES, WEIGHTS):
        declarations.append(f'{card} {{ --od-{key}: calc(var(--od-space) * {weight / sum(WEIGHTS):.12f} + var(--od-tile-edge)); }}')
        declarations.append(f'{card} [data-metric="{key}"] {{ flex: 0 0 var(--od-{key}) !important; }}')
    removed = ' - '.join(f'var(--od-{key})' for key in hidden)
    width = f'calc(100cqw - {removed} - {min(len(hidden), 5) * .22:.2f}rem)'
    if len(hidden) == len(CAPSULES):
        width = 'max-content'
        declarations.append(f'{card} [data-role="capsules"] {{ display: none !important; }}')
    declarations.append(f'{card} {{ width: {width} !important; }}')
    return start + '\n' + '\n'.join(declarations) + '\n' + end + '\n' + css


def rule(agent, capsule):
    if agent not in AGENTS or capsule not in CAPSULES:
        raise ValueError('Unknown chyron capsule')
    return (f'/* opendeck-capsule:{agent}:{capsule} */\n'
            f'[data-agent="{agent}"] [data-metric="{capsule}"] '
            '{ display: none !important; }\n'
            f'/* /opendeck-capsule:{agent}:{capsule} */')


def read(client, settings):
    result = client.get_input_settings(settings['source'])
    if result.input_kind != 'browser_source':
        raise ValueError('Chyron must be an OBS browser source')
    css = result.input_settings.get('css', '')
    if not isinstance(css, str):
        raise ValueError('Invalid browser CSS')
    block = rule(settings['agent'], settings['capsule'])
    # Refuse damaged/hand-edited managed rules instead of adding a conflicting one.
    marker = f'opendeck-capsule:{settings["agent"]}:{settings["capsule"]}'
    if css.count(marker) != 2 * css.count(block) or css.count(block) > 1:
        raise ValueError('Modified capsule visibility rule')
    return css, block


def enabled(client, settings):
    css, block = read(client, settings)
    return block not in css


def toggle(client, settings):
    css, block = read(client, settings)
    # Prefixing makes removal byte-for-byte reversible, including trailing whitespace.
    updated = css.replace(block + '\n', '', 1) if block + '\n' in css else (
        css.replace(block, '', 1) if block in css else block + '\n' + css)
    updated = compact_css(updated, settings['agent'])
    client.set_input_settings(settings['source'], {'css': updated}, overlay=True)
