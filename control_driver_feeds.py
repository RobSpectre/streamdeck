#!/bin/python
import os

import click

import json

with open('current_drivers.json') as f:
    current_drivers = json.load(f)

with open('drivers.json') as f:
    drivers = json.load(f)

maximize_string = "xdotool search --onlyvisible --name '{0}' windowactivate --sync key F11"
change_string = "./change_driver.sh {0} {1} {2}"

mouse_coordinates = [
  {'x': 8301,
   'y': 1040},
  {'x': 9601,
   'y': 1040},
  {'x': 10890,
   'y': 1040},
  {'x': 8301,
   'y': 1772},
  {'x': 9601,
   'y': 1772},
  {'x': 10890,
   'y': 1772}
]

@click.group()
def cli():
    pass

@click.command()
@click.option("--driver_window",
              default=0,
              help="Maximize specific driver window.")
def maximize_driver(driver_window):
    driver_search_string = current_drivers['drivers'][driver_window]['name']
    os.system(maximize_string.format(driver_search_string))


@click.command()
@click.option("--driver_abbreviation",
              default=None,
              help="Change window to this driver.")
def change_driver(driver_abbreviation):
    target_driver = drivers[driver_abbreviation]
    driver_window = current_drivers['target_window']

    os.system(change_string.format(target_driver['index'],
                                   mouse_coordinates[driver_window]['x'], 
                                   mouse_coordinates[driver_window]['y']))

    current_drivers['drivers'][driver_window] = { 'name': target_driver['name'] }

    with open('current_drivers.json', 'w') as f:
        json.dump(current_drivers, f)


@click.command()
@click.option("--driver_window",
              default=0,
              help="Target driver window.")
def target_window(driver_window):
    current_drivers['target_window'] = driver_window

    with open('current_drivers.json', 'w') as f:
        json.dump(current_drivers, f)


cli.add_command(maximize_driver)
cli.add_command(change_driver)
cli.add_command(target_window)


if __name__ == '__main__':
    cli()
