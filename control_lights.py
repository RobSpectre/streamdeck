import click

import leglight

import json

config = open('lights.json')
lights = json.load(config)


@click.group()
def cli():
    pass


@click.command()
@click.option("--light",
              default=None,
              help="Label of light to turn on.")
def on(light):
    if light:
        light = leglight.LegLight(lights[light]['address'], 9123)
        light.on()
    else:
        for light in lights:
            light = leglight.LegLight(lights[light]['address'], 9123)
            light.on()


@click.command()
@click.option("--light",
              default=None,
              help="Label of light to turn off.")
def off(light):
    if light:
        light = leglight.LegLight(lights[light]['address'], 9123)
        light.off()
    else:
        for light in lights:
            light = leglight.LegLight(lights[light]['address'], 9123)
            light.off()


@click.command()
@click.option("--light",
              default=None,
              help="Label of light to toggle on or off.")
def toggle(light):
    if light:
        light = leglight.LegLight(lights[light]['address'], 9123)

        if light.isOn:
            light.off()
        else:
            light.on()
    else:
        for light in lights:
            light = leglight.LegLight(lights[light]['address'], 9123)

            if light.isOn:
                light.off()
            else:
                light.on()


@click.command()
@click.option("--light",
              default=None,
              help="Label of light to dim.")
@click.option("--amount",
              default=5,
              help="Amount to dim light in percentage points.")
def dim(light, amount):
    if light:
        light = leglight.LegLight(lights[light]['address'], 9123)

        if (light.isBrightness - amount) > 0:
            light.brightness(light.isBrightness - amount)
        else:
            light.brightness(0)
    else:
        for light in lights:
            light = leglight.LegLight(lights[light]['address'], 9123)

            if (light.isBrightness - amount) > 0:
                light.brightness(light.isBrightness - amount)
            else:
                light.brightness(0)


@click.command()
@click.option("--light",
              default=None,
              help="Label of light to brighten.")
@click.option("--amount",
              default=5,
              help="Amount to brighten light in percentage points.")
def brighten(light, amount):
    if light:
        light = leglight.LegLight(lights[light]['address'], 9123)

        if (light.isBrightness + amount) > 100:
            light.brightness(100)
        else:
            light.brightness(light.isBrightness + amount)
    else:
        for light in lights:
            light = leglight.LegLight(lights[light]['address'], 9123)

            if (light.isBrightness + amount) > 100:
                light.brightness(100)
            else:
                light.brightness(light.isBrightness + amount)


@click.command()
@click.option("--light",
              default=None,
              help="Label of light to dim.")
@click.option("--amount",
              default=100,
              help="Amount to warm light in Kelvin.")
def warm(light, amount):
    if light:
        light = leglight.LegLight(lights[light]['address'], 9123)

        if (light.isTemperature- amount) > 2900:
            light.color(light.isTemperature - amount)
        else:
            light.color(2900)
    else:
        for light in lights:
            light = leglight.LegLight(lights[light]['address'], 9123)

            if (light.isTemperature - amount) > 2900:
                light.color(light.isTemperature - amount)
            else:
                light.color(2900)


@click.command()
@click.option("--light",
              default=None,
              help="Label of light to dim.")
@click.option("--amount",
              default=100,
              help="Amount to warm light in percentage points.")
def cool(light, amount):
    if light:
        light = leglight.LegLight(lights[light]['address'], 9123)

        if (light.isTemperature + amount) > 7000:
            light.color(7000)
        else:
            light.color(light.isBrightness + amount)
    else:
        for light in lights:
            light = leglight.LegLight(lights[light]['address'], 9123)

            if (light.isTemperature + amount) > 7000:
                light.color(7000)
            else:
                light.color(light.isTemperature + amount)


cli.add_command(on)
cli.add_command(off)
cli.add_command(toggle)
cli.add_command(dim)
cli.add_command(brighten)
cli.add_command(warm)
cli.add_command(cool)


if __name__ == '__main__':
    cli()
