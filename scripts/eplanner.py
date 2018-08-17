#!/usr/bin/env python

from __future__ import print_function

usage = \
""" Plots out observing schedules, with a focus on periodic events. You
supply a file of target positions and ephemerides, another defining phase
ranges of interest and optionally a third specifying when to switch targets,
and this will make a graphical representation of the results.

The tracks for the stars start and stop when they reach a user-defined
airmass, set to 2.2 by default, or when the Sun is 10 degrees below the
horizon, whichever is more constraining. Sun at -10 is optimistic for most
targets.

If you see horizontal black error bars at the far right, these indicate +/- 1
sigma uncertainties on ephemerides. As quoted uncertainties can barely ever be
trusted, they are indicative only. If they are big, be careful: your eclipse
may not appear when you expect.

Grey boxes represent zenith holes for Alt/Az telescopes which can't track very
close to the zenith. These are not always hard limits, but you may not be able
to observe during these intervals. For the TNT there is also a special
indicator of close approach to the TV mast (only approximate).

A curved, red dashed line represents the elevation of the Moon. An indication of
its illuminated percentage is written at the top and its minimum separation from
targets is indicated if it is below a user-defined minimum.

Black dots indicate phase 0 for any targets with ephemerides.
"""
import argparse
import datetime

import numpy as np

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MultipleLocator, FuncFormatter

from astropy import time, coordinates as coord, units as u
from astropy.coordinates import get_sun, get_moon, EarthLocation, AltAz

from trm import observing
from trm.observing import SITES

def utc_formatter(x, pos):
    """
    Make sure UTC labels are always in range 1-24
    """
    if int(x) > 24:
        x -= 24
    return '{:d}'.format(int(x))


if __name__ == '__main__':

    # arguments
    parser = argparse.ArgumentParser(
        description=usage,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    # positional
    parser.add_argument(
        'stardata',
        help='file containing positions and ephemerides. It should have the same format of my C++ ephemeris file.')

    parser.add_argument(
        'telescope', help='Telescope name, e.g. WHT, NTT, VLT, TNT')

    parser.add_argument(
        'pranges',
        help='file of stars to include and phase ranges of interest. Each entry should start with the name of the star on its own on a line, and then follow it with the phase ranges in the form:\np1 p2 col lw\nwhere p1 p2 is the range of phase to indicate, col is the pgplot colour index (2 = red, etc), lw is the pgplot line width. It is OK to have p1 > p2; the programme will map it into a positive range.')

    parser.add_argument(
        'date', help='date at start of night, format: "YYYY-MM-DD"')

    # optional
    parser.add_argument(
        '-f', dest='hcopy', default=None,
        help='Name for hard copy file, e.g. plot.pdf, plot.png (there will be no interactive plot in this case)')

    parser.add_argument(
        '-t', dest='twilight', type=float, default=-15,
        help='altitude of Sun for twilight [degrees]')

    parser.add_argument(
        '-m', dest='mdist', type=float, default=20,
        help='separation below which to highlight that the Moon gets close [degrees]')

    parser.add_argument(
        '-c', dest='csize', type=float, default=1.0,
        help='default character size for star names')

    parser.add_argument(
        '-a', dest='airmass', type=float, default=2.2,
        help='airmass limit.')

    parser.add_argument(
        '-o', dest='offset', type=float, default=0.3,
        help='offset as fraction of plot width at which to print duplicate names.')

    parser.add_argument(
        '-d', dest='divide', type=float, default=0.18,
        help='divide point between names on left and plot on right as fraction of total width')

    parser.add_argument(
        '--hfrac', type=float, default=0.84,
        help='plot height as fraction of total')

    parser.add_argument(
        '--bfrac', type=float, default=0.08,
        help='offset of bottom of plot as fraction of total')

    parser.add_argument(
        '--xmajor', type=float, default=2,
        help='spacing of labelled major ticks in X [hours]')

    parser.add_argument(
        '--xminor', type=float, default=1,
        help='spacing of minor ticks in X [hours]')

    parser.add_argument(
        '-p', dest='prefix', default=None,
        help='target name prefixes. These are placed before the left-hand list of target names to allow one to add e.g. priorities.')

    parser.add_argument(
        '-s', dest='switch', default=None,
        help='switch targets data file name. Each line should have the format:\nstar name | start switch time (e.g. 12:34) | dead time\nwhere the dead time is the time taken (in minutes) to make the switch. The line will be split on the pipe | characters which must therefore not appear in the star name. Use a star name = None as the final switch to terminate early. The times should increase monotonically, so use times > 24 if necessary.')

    parser.add_argument(
        '-x', dest='width', type=float, default=11.69,
        help='plot width, inches')

    parser.add_argument(
        '-y', dest='height', type=float, default=8.27,
        help='plot height, inches')

    # parse them
    args = parser.parse_args()

    # a few checks
    assert(args.airmass > 1 and args.airmass < 6)
    assert(args.width > 0 and args.height > 0)
    assert(args.telescope in SITES)

    # Interpret date. 
    date = time.Time(args.date, out_subfmt='date')

    # Location
    info = SITES[args.telescope]
    site = coord.EarthLocation.from_geodetic(
        info['long'], info['lat'], info['height']
    )

    # Load position and ephemeris data
    peinfo = observing.load_pos_eph(args.stardata)

    # Load phase / time ranges
    prinfo = observing.load_ptranges(args.pranges, peinfo)

    # Load switches
    swinfo = observing.load_switches(args.switch, peinfo)

    # Load prefixes
    prefixes = observing.load_prefixes(args.prefix, peinfo)

    # Compute maximum length of the names
    if len(prefixes):
        mpre = max([len(n) for n in prefixes.values()]) + 1
    else:
        mpre = 0

    left = max([len(n) for n in peinfo.keys()]) + mpre

    # Rather primitive times to bracket Sun down and up; won't work properly
    # in far north or south or around the dateline, but should be OK for most
    # sites.  'date' is set at the UTC of the start of the entered date,
    # i.e. 0 hours. To get to the day time before the night of interest, we
    # advance by 0.5 days and apply an offset in longitude. This should be the
    # local mid-day, then half day steps are used to locate midnight and the
    # following mid day. Armed with these we can narrow down on the sunset /
    # rise etc times.
    toffset = time.TimeDelta(0.5 - site.lon.degree/360., format='jd')

    day1  = date + toffset
    night = day1 + time.TimeDelta(0.5, format='jd')
    day2  = night + time.TimeDelta(0.5, format='jd')

    # sunset & sunrise times
    sunset = observing.sun_at_alt(day1, night, site, -0.25)
    sunrise = observing.sun_at_alt(night, day2, site, -0.25)
    sunset.out_subfmt='date_hm'
    sunrise.out_subfmt='date_hm'

    # integer offset
    isun = int(sunset.mjd)
    utc1 = 24.*(sunset.mjd-isun)
    utc2 = 24.*(sunrise.mjd-isun)
    print('Sun is at alt=-0.25 at {0:s} and {1:s}'.format(sunset.iso,sunrise.iso))

    # the lines in the plot will terminate at the point the Sun is at -10 as
    # the absolute limit for observation.
    rset = observing.sun_at_alt(day1, night, site, -10.)
    rrise = observing.sun_at_alt(night, day2, site, -10.)
    rset.out_subfmt='date_hm'
    rrise.out_subfmt='date_hm'
    utc5 = 24.*(rset.mjd-isun)
    utc6 = 24.*(rrise.mjd-isun)
    print('Sun is at alt=-10.0 at {0:s} and {1:s}'.format(rset.iso,rrise.iso))

    # user-defined twilight -- will be indicated on the plot with dashed lines
    twiset = observing.sun_at_alt(day1, night, site, args.twilight)
    twirise = observing.sun_at_alt(night, day2, site, args.twilight)
    twiset.out_subfmt='date_hm'
    twirise.out_subfmt='date_hm'
    utc3 = 24.*(twiset.mjd-isun)
    utc4 = 24.*(twirise.mjd-isun)
    print('Sun is at alt={0:5.1f} at {1:s} and {2:s}'.format(args.twilight,twiset.iso,twirise.iso))

    # simulate the old PGPLOT colours
    cols = {
        2 : (0.7,0,0),
        3 : (0,0.7,0),
        4 : (0,0,0.7),
        5 : (0.7,0.7,0.7),
        9 : (0.8,0.8,0.8),
    }

    # Start the plot
    fig = plt.figure(figsize=(args.width,args.height),facecolor='white')

    # left and right axes. Left for labels, right for the main stuff
    edge = 0.04
    axl = plt.axes([edge, args.bfrac, args.divide, args.hfrac])
    axr = plt.axes([args.divide+edge, args.bfrac, 1-2*edge-args.divide,
                    args.hfrac], frameon=False)

    # correct switch times to lie within range
    for sw in swinfo:
        if sw.utc < utc1 and sw.utc+24 < utc2:
            sw.utc += 24.

    # set up general scale, draw vertical dashed lines every minor 
    # tick spacing
    utstart = utc1 - 0.5
    utend = utc2 + 0.5

    n1 = int(np.ceil(utc1/args.xminor))
    n2 = int(np.ceil(utc2/args.xminor))

    for n in range(n1,n2):
        axr.plot([n*args.xminor,n*args.xminor],[0,1],'--',color=cols[5])

    # mark sunset / twiset / twirise / sunrise

    # first with vertical lines
    kwargs = {'color' : cols[2]}
    axr.plot([utc1,utc1],[0,1],'--',**kwargs)
    axr.plot([utc2,utc2],[0,1],'--',**kwargs)
    axr.plot([utc3,utc3],[0,1],'--',**kwargs)
    axr.plot([utc4,utc4],[0,1],'--',**kwargs)

    # then labels
    kwargs = {'color' : cols[2], 'ha' : 'center', 'va' : 'center', 
              'size' : 10}
    axr.text(utc1, 1.02, 'sunset', **kwargs)
    axr.text(utc2, 1.02, 'sunrise', **kwargs)
    axr.text(utc3, 1.02, str(args.twilight), **kwargs)
    axr.text(utc4, 1.02, str(args.twilight), **kwargs)

    # 1000 points from start to end defined by the Sun at -10.
    utcs = np.linspace(utc5,utc6,1000)
    mjds = isun + utcs/24.
    mjds = time.Time(mjds, format='mjd')

    # Calculate MJD in middle of visibility period and the position of the
    # Moon at this time in order to calculate a representative illumination
    # for the Moon which is added at the top of the plot.
    mjd_mid = time.Time(isun + (utc5+utc6)/48., format='mjd')

    moon = get_moon(mjd_mid, location=site)
    sun = get_sun(mjd_mid)
    elong = sun.separation(moon)
    mphase = np.arctan2(sun.distance*np.sin(elong),
                        moon.distance - sun.distance*np.cos(elong))
    illum = (1 + np.cos(mphase))/2.0
    axr.text((utc5+utc6)/2., 1.02,
             'Moon: {:3d}%'.format(int(round(100*illum.value))), **kwargs)

    # Loop through the stars listed in the ephemeris file, computing their hour
    # angles at midnight to establish the plot order
    has = []
    lst = mjd_mid.sidereal_time(kind='mean', longitude=site.lon)

    for key, star in peinfo.items():
        ha = (lst - star.position.ra).value
        if ha > 12.: ha -= 24
        if ha < -12.: ha += 24
        has.append((ha, key))

    keys = [item[1] for item in sorted(has, key=lambda ha: ha[0], reverse=True)]

    # Now compute plot positions
    ys = {}
    for i,key in enumerate(keys):
        ys[key] = (len(keys)-i)/float(len(keys)+1)

    # Plot a line to represent which target to observe
    if args.switch is not None:
        kwargs = {'color' : cols[5], 'lw' : 5}

        first = True
        for sw in swinfo:
            if first:
                xstart, ystart = sw.utc,ys[sw.name]
                first = False
            else:
                if sw.name == 'None':
                    axr.plot([xstart,sw.utc],[ystart,ystart],**kwargs)
                    break
                else:
                    xend, yend = sw.utc+sw.delta, ys[sw.name]
                    axr.plot([xstart, sw.utc, xend],[ystart, ystart, yend],**kwargs)
                    xstart, ystart = xend, yend

    # compute altitude of Moon through the night. Add as red dashed line
    # scaled so that 90 = top of plot.
    moon = get_moon(mjds, location=site)
    altazframe = AltAz(obstime=mjds, location=site)
    altaz = moon.transform_to(altazframe)
    alts = altaz.alt.value
    plt.plot(utcs,alts/90.,'--',color=cols[2])

    # Finally, loop through the stars listed in the phase ranges.
    for key in keys:
        star = peinfo[key]
        y = ys[key]

        # Compute airmasses for all times
        altaz = star.position.transform_to(altazframe)
        airmasses = altaz.secz.value
        alts = altaz.alt.value
        azs = altaz.az.value
        ok = alts > 90.-np.degrees(np.arccos(1./args.airmass))

        # Compute minimum distance to the Moon during period target
        # is above airmass limit
        seps = moon.separation(star.position).degree[ok]
        if len(seps):
            sepmin = seps.min()
            moon_close = sepmin < args.mdist
            if moon_close:
                col = cols[2]
            else:
                col = 'k'
        else:
            moon_close = False

        first = True
        afirst = True
        for flag, utc, mjd in zip(ok, utcs, mjds):
            if first and flag:
                ut_start = utc
                first = False
                if afirst:
                    mjd_first = mjd
                    utc_first = utc
                    afirst = False
            elif not flag and not first:
                first = True
                axr.plot([ut_start,utc],[y,y],'--',color=col)
                lbar = min(0.01, 1./len(keys)/4.)
                axr.plot([ut_start,ut_start],[y-lbar,y+lbar],color=col)
                axr.plot([utc,utc],[y-lbar,y+lbar],color=col)
                mjd_last = mjd
                utc_last = utc

                if ut_start > utstart + args.offset*(utend-utstart):
                    # repeat target name if the start is delayed to make it
                    # easier to line up names and tracks
                    kwargs = {'ha' : 'right', 'va' : 'center',
                              'size' : 9*args.csize}
                    axr.text(ut_start-0.2, y, key, **kwargs)

        if flag and not first:
            # stuff left over to plot
            axr.plot([ut_start,utc],[y,y],'--',color=col)
            lbar = min(0.01, 1./len(keys)/4.)
            axr.plot([ut_start,ut_start],[y-lbar,y+lbar],color=col)
            axr.plot([utc,utc],[y-lbar,y+lbar],color=col)
            mjd_last = mjd
            utc_last = utc

            if ut_start > utstart + args.offset*(utend-utstart):
                # repeat target name if the start is delayed to make it
                # easier to line up names and tracks
                kwargs = {'ha' : 'right', 'va' : 'center',
                          'size' : 9*args.csize}
                axr.text(ut_start-0.2, y, key, **kwargs)

        if afirst:
            # never found any ok bit; move on ...
            continue

        if moon_close:
            axr.text(utc_last+0.07, y,
                     '${:d}^\circ$'.format(int(round(sepmin))),
                     ha='left', va='center', size=9*args.csize,
                     color=cols[2])

        # zenith holes
        start = True
        for alt, utc in zip(alts[ok], utcs[ok]):
            if start and alt > 90.-info['zhole']:
                air_start = utc
                start = False
            elif not start and alt < 90.-info['zhole']:
                air_end = utc
                break

        if not start:
            plt.fill([air_start,air_end,air_end,air_start],
                     [y-0.01,y-0.01,y+0.01,y+0.01], color=cols[9])
            plt.plot([air_start,air_end,air_end,air_start,air_start],
                     [y-0.01,y-0.01,y+0.01,y+0.01,y-0.01], color='k',lw=0.8)

        # TNT has a stupid TV aerial
        if args.telescope == 'TNT':
            start = True
            aerial = []
            for alt,az,utc in zip(alts[ok],azs[ok],utcs[ok]):
                if az < 0.: az += 360.

                if observing.tnt_alert(alt, az):
                    if start:
                        # start bad period
                        air_start = utc
                        air_end   = utc
                        start     = False
                    else:
                        # update end time of bad period
                        air_end = utc
                else:
                    if not start:
                        # We are out of it. Record bad period.
                        aerial.append((air_start,air_end))
                        start = True

            if not start:
                # We were still in a bad period at the end. Record it.
                aerial.append((air_start,air_end))

            # Plot the bad periods
            for air_start, air_end in aerial:
                axr.fill([air_start,air_end,air_end,air_start],
                         [y-0.01,y-0.01,y+0.01,y+0.01], color=cols[9])
                axr.plot([air_start,air_end,air_end,air_start,air_start],
                         [y-0.01,y-0.01,y+0.01,y+0.01,y-0.01], color='k',lw=0.8)

        if key in prinfo:
            # handles the time ranges only
            pr = prinfo[key]

            pranges = pr.prange
            for t1, t2, col, lw, p_or_t in pranges:
                if p_or_t == 'Time':
                    utc1, utc2 = 24.*(t1-isun), 24.*(t2-isun)
                    if utc1 < utc_end and utc2 > utc_start:
                        ut1  = max(utc1, utc_start)
                        ut2  = min(utc2, utc_end)
                        if ut1 < ut2:
                            plt.plot([ut1,ut2],[y,y],color=cols[col],lw=lw)

        if star.eph:
            # Now the phase info

            eph = star.eph
            times = time.Time((mjd_first,mjd_last),location=site)
            if eph.time.startswith('H'):
                times += times.light_travel_time(star.position, 'heliocentric')
            elif eph.time.startswith('B'):
                times += times.light_travel_time(star.position)
            else:
                raise Exception('Unrecognised type of time = ' + eph.time)

            if eph.time == 'HJD' or eph.time == 'BJD':
                pstart = eph.phase(times[0].jd)
                pend   = eph.phase(times[1].jd)
            elif eph.time == 'HMJD' or eph.time == 'BMJD':
                pstart = eph.phase(times[0].mjd)
                pend   = eph.phase(times[1].mjd)
            else:
                raise Exception('Unrecognised type of time = ' + eph.time)

            # Compute uncertainty in predictions
            delta = 24.*min(eph.etime((pstart+pend)/2.), eph.coeff[1]/2.)
            if delta > 0.03:
                plt.plot([utend-2.*delta,utend],[y,y],'k',lw=2)
                plt.plot([utend-2.*delta,utend-2*delta],[y-0.005,y+0.005],'k',lw=2)
                plt.plot([utend,utend],[y-0.005,y+0.005],'k',lw=2)

            if key in prinfo:
                pr   = prinfo[key]

                # Draw phase ranges of interest
                pranges = pr.prange
                for p1, p2, col, lw, p_or_t in pranges:
                    if p_or_t == 'Phase':
                        d1 = pstart + (p1 - pstart) % 1 - 1
                        d2 = pend + (p1 - pend) % 1
                        nphs = int(np.ceil(d2 - d1))
                        for n in range(nphs):
                            ut1 = utc_first + (utc_last-utc_first)*(d1 + n - pstart)/(pend-pstart)
                            ut2  = ut1 + (utc_last-utc_first)/(pend-pstart)*(p2-p1)
                            ut1  = max(ut1, utc_first)
                            ut2  = min(ut2, utc_last)
                            if ut1 < ut2:
                                plt.plot([ut1,ut2],[y,y],color=cols[col],lw=lw)

            # draws dots at phase zero
            d1 = np.ceil(pstart)
            d2 = np.floor(pend)
            nphs = int(np.ceil(d2 - d1))+1
            for n in range(nphs):
                ut = utc_first + (utc_last-utc_first)*(d1 + n - pstart)/(pend-pstart)
                plt.plot(ut,y,'ok',ms=4)

        # draw vertical bar at meridian crossing
        if ok.any():
            lst = mjds.sidereal_time(kind='mean', longitude=site.lon)
            has = (lst - star.position.ra).value
            hamin, hamax = has[ok].min(), has[ok].max()
            if hamin < 0 and hamax > 0.:
                has = np.abs(has[ok])
                utc_mer = utcs[ok][has.argmin()]
                plt.plot([utc_mer,utc_mer],[y-1.3*lbar,y+1.3*lbar],'k',lw=2)

    # finish off
    axr.set_xlabel('UTC')
    axr.set_title('{0!s} ({1:s}, airmass < {2:3.1f})'.format(
        date, args.telescope, args.airmass))

    axr.set_xlim(utstart, utend)
    axr.set_ylim(0,1.05)

    axr.xaxis.set_major_locator(MultipleLocator(args.xmajor))
    axr.xaxis.set_minor_locator(MultipleLocator(args.xminor))
    axr.xaxis.set_major_formatter(FuncFormatter(utc_formatter))
    axr.get_xaxis().tick_bottom()
    axr.axes.get_yaxis().set_visible(False)
    fig.canvas.draw()

    # add target names at left
    for key in keys:
        y = ys[key]
        if key in prefixes:
            name = prefixes[key] + ' ' + key
        elif len(prefixes):
            name = mpre*' ' + key
        else:
            name = key
        axl.text(0.95,y,name,ha='right',va='center',size=9*args.csize)
    axl.set_xlim(0,1)
    axl.set_ylim(0,1.05)
    axl.set_axis_off()

    xmin, xmax = axr.get_xaxis().get_view_interval()
    ymin, ymax = axr.get_yaxis().get_view_interval()
    axr.add_artist(
        Line2D((xmin, xmax), (ymin, ymin), color='black',
               linewidth=2))

    if args.hcopy:
        plt.savefig(args.hcopy)
    else:
        plt.show()
