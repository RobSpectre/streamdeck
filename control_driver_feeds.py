#!/bin/python
import click

import json

import time

from mvf1 import MultiViewerForF1

with open('state.json') as f:
    state = json.load(f)

remote = MultiViewerForF1()

window_bounds = [
    {'x': 7680, 'y': 0, 'width': 1027, 'height': 580, 'occupied': False},
    {'x': 9217, 'y': 0, 'width': 1027, 'height': 580, 'occupied': False},
    {'x': 10753, 'y': 0, 'width': 1024, 'height': 579, 'occupied': False},
    {'x': 7680, 'y': 573, 'width': 1024, 'height': 579, 'occupied': False},
    {'x': 9217, 'y': 573, 'width': 1024, 'height': 579, 'occupied': False},
    {'x': 10753, 'y': 573, 'width': 1024, 'height': 579, 'occupied': False},
    {'x': 7680, 'y': 1147, 'width': 1025, 'height': 579, 'occupied': False},
    {'x': 9217, 'y': 1147, 'width': 1025, 'height': 579, 'occupied': False},
    {'x': 10753, 'y': 1147, 'width': 1025, 'height': 579, 'occupied': False}
]

players = remote.players

drivers_currently_fullscreen = [p.title for p in players if p.fullscreen and len(p.title) == 3]
drivers = [p.title for p in players if len(p.title) == 3]
drivers_currently_on_top = [p.title for p in players if p.always_on_top and len(p.title) == 3]

for i, bound in enumerate(window_bounds):
    for player in players:
        if bound['x'] == player.bounds['x'] \
           and bound['y'] == player.bounds['y']:
            bound['occupied'] = True
            player.quadrant = i

def target_driver(driver_abbreviation):
    click.echo(f"Targeting {driver_abbreviation}...")
    state['target_window'] = driver_abbreviation
    state['command'] = "change" 

    with open('state.json', 'w') as f:
        json.dump(state, f)


def maximize_driver(driver_abbreviation, set_history=True):
    for player in players:
        if player.title == driver_abbreviation:
            click.echo(f"Toggling {player.title} fullscreen...")
            player.set_fullscreen()
            player.set_always_on_top(always_on_top=False)

            state['target_window'] = driver_abbreviation
            state['command'] = None 

            if set_history:
                state['history'].append({
                    'driver_abbreviation': player.title,
                    'x': player.x,
                    'y': player.y,
                    'width': player.width,
                    'height': player.height
                })

            with open('state.json', 'w') as f:
                json.dump(state, f)

    click.echo("Done.")


def change_driver(driver_abbreviation):
    player = get_player_by_abbreviation(state['target_window'])

    click.echo(f"Switching {player.title} to {driver_abbreviation}...")
    player.switch_stream(driver_abbreviation)

    time.sleep(0.5)

    remote.player_sync_to_commentary()

    state['target_window'] = driver_abbreviation
    state['command'] = None 

    with open('state.json', 'w') as f:
        json.dump(state, f)

    click.echo("Done.")

def get_player_by_abbreviation(driver_abbreviation):
    for player in players:
        if player.title == driver_abbreviation:
            return player

    return None

def return_driver_to_previous_position(driver_abbreviation):
    player = get_player_by_abbreviation(driver_abbreviation)

    for entry in state['history']:
        if entry['driver_abbreviation'] == driver_abbreviation:
            player.set_bounds(x=entry['x'],
                              y=entry['y'],
                              width=entry['width'],
                              height=entry['height'])
            player.set_always_on_top(always_on_top=False)

    for driver in drivers_currently_fullscreen:
        player = get_player_by_abbreviation(driver)
        player.set_always_on_top(always_on_top=True)
        player.set_always_on_top(always_on_top=False)


def set_driver_above_fullscreen(driver_abbreviation,
                                set_history=True):
    player = get_player_by_abbreviation(driver_abbreviation)
    bounds = window_bounds[3 * len(drivers_currently_on_top)]

    if set_history:
        state['history'].append({
            'driver_abbreviation': player.title,
            'x': player.x,
            'y': player.y,
            'width': player.width,
            'height': player.height
        })

        with open('state.json', 'w') as f:
            json.dump(state, f)

    player.set_bounds(x=bounds['x'],
                      y=bounds['y'],
                      width=bounds['width'],
                      height=bounds['height'])
    player.set_always_on_top(always_on_top=True)


def minimize_drivers(driver_abbreviation):
    open_bounds = [b for b in window_bounds if not b['occupied']]

    for driver in drivers_currently_on_top:
        return_driver_to_previous_position(driver)

    for driver in drivers_currently_fullscreen:
        click.echo("Going through fullscreen drivers...")
        player = get_player_by_abbreviation(driver)

        player.set_fullscreen()
        player.set_always_on_top(always_on_top=False)


@click.group()
def cli():
    pass


@click.command(help="Driver entry point.")
@click.option('--driver_abbreviation')
def driver(driver_abbreviation):
    click.echo(f"Evaluating request for {driver_abbreviation}...")

    click.echo(f"Drivers in full screen: {drivers_currently_fullscreen}")
    click.echo(f"Drivers currently on top: {drivers_currently_on_top}")
    click.echo(f"Drivers currently playing: {drivers}")

    if state['command'] == "target":
        target_driver(driver_abbreviation)
    elif state['command'] == "change" \
            and driver_abbreviation not in drivers:
        change_driver(driver_abbreviation)
    elif driver_abbreviation in drivers:
        if driver_abbreviation in drivers_currently_fullscreen:
            minimize_drivers(driver_abbreviation)
        elif driver_abbreviation in drivers_currently_on_top:
            return_driver_to_previous_position(driver_abbreviation)
        elif drivers_currently_fullscreen and driver_abbreviation not in drivers_currently_fullscreen:
            set_driver_above_fullscreen(driver_abbreviation)
        else:
            maximize_driver(driver_abbreviation)

    click.echo("Done.")


@click.command(help="Set the command bit to target a driver.")
def set_target():
    state['command'] = "target"

    with open('state.json', 'w') as f:
        json.dump(state, f)


@click.command(help="Toggle mute on commentary and driver radio.")
def toggle_driver_radio():
    target_driver = state['target_window']

    for player in remote.players:
        if player.title == target_driver:
            player.mute()
        elif player.title == 'INTERNATIONAL':
            if player.state['volume'] > 10:
                player.set_volume(10)
            else:
                player.set_volume(37)

@click.command(help="Rotate driver feeds currently featured.")
def rotate_drivers():
    click.echo(f"Drivers in full screen: {drivers_currently_fullscreen}")
    click.echo(f"Drivers currently on top: {drivers_currently_on_top}")

    players_on_top = [get_player_by_abbreviation(d) for d in drivers_currently_on_top]
    players_on_top = sorted(players_on_top, key=lambda p: p.y)
    click.echo(f"Player order: {players_on_top}")

    click.echo(f"Minimizing {drivers_currently_fullscreen[0]}...")
    minimize_drivers(drivers_currently_fullscreen[0])

    maximize_driver(players_on_top[0].title, set_history=False)
    click.echo(f"Maximizing {players_on_top[0].title}...")

    for i, driver in enumerate([p.title for p in players_on_top][1:] +
                               drivers_currently_fullscreen):
        click.echo(f"Moving {driver}")
        bounds = window_bounds[3 * i]
        player = get_player_by_abbreviation(driver)

        player.set_bounds(x=bounds['x'],
                          y=bounds['y'],
                          width=bounds['width'],
                          height=bounds['height'])
        player.set_always_on_top(always_on_top=True)


cli.add_command(set_target)
cli.add_command(driver)
cli.add_command(toggle_driver_radio)
cli.add_command(rotate_drivers)

if __name__ == '__main__':
    cli()
