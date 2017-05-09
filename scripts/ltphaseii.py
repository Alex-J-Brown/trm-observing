#!/usr/bin/env python

usage = \
"""
Prints out the data needed for the LT phase II given phase constraints.  LT do
not include light travel time corrections so this asks for a period of
interest and comes up with a zero-point and mean period which accounts for
it. Keep the interval to no more than a month or so, depending upon the target
position and time of year (just experiment). It adjusts the zeropoint so that
in the LT phase II you should use a "phase" of zero.
"""

import math
import argparse
from trm import subs, sla, observing

# arguments
parser = argparse.ArgumentParser(description=usage,\
                                 formatter_class=argparse.ArgumentDefaultsHelpFormatter)

# positional
parser.add_argument('stardata', type=argparse.FileType('r'),
                   help='general file containing positions and ephemerides. It should have the same format as my C++ ephemeris file.')

parser.add_argument('obsinfo', type=argparse.FileType('r'),
                    help='observational info: "name | start phase | end phase | exp time (secs) | window (mins) | start date | end date" for each star.')

# optional
parser.add_argument('-t', dest='telescope', default='LT', help='Telescope name, e.g. WHT, VLT. Default = LT')

# parse them
args = parser.parse_args()

# Get observatory parameters
tel,obs,longit,latit,height = subs.observatory(args.telescope)

# Load position and ephemeris data
peinfo = {}
count = 0
nline = 0
name  = None
for line in args.stardata:
    nline += 1
    try:
        if not line.startswith('#') and not line.isspace():
            count += 1
            if count == 1:
                name = line.strip()
            elif count == 2:
                ra,dec,system = subs.str2radec(line.strip())
            elif count == 3:
                # Position-based key for RA-ordering later
                key = subs.d2hms(ra,dp=2) + ' ' + subs.d2hms(dec,dp=1,sign=True)
                eph = observing.Ephemeris(line)
                peinfo[key] = {'name' : name, 'ephemeris' : eph, 'ra' : ra, 'dec' : dec}
                count = 0
    except Exception, err:
        print err
        print 'Line number',nline
        print 'Line =',line.strip()
        if name:
            print 'Name = ' + name
        else:
            print 'Name undefined'
        print 'Program aborted.'
        exit(1)

args.stardata.close()
print 'Data on',len(peinfo),'stars loaded.'

# Load observational info
obsinfo = {}
for line in args.obsinfo:
    if not line.startswith('#') and not line.isspace():
        try:
            name, p1, p2, expose, window, start, end = line.split('|')
            obsinfo[name.strip()] = {
                'p1' : float(p1), 'p2' : float(p2), 
                'expose' : float(expose), 'window' : float(window),
                'start' : start.strip(), 'end' : end.strip()}
        except Exception, err:
            print err
            print 'Line =',line.strip()
            print 'Program aborted.'
            exit(1)

args.obsinfo.close()
print len(obsinfo),'phase range / exposure / window lines loaded.\n'

# check all targets have phase ranges
for star in peinfo.values():
    if star['name'] not in obsinfo:
        print 'No phase range and exposure time specified for',star['name']
        exit(1)

# Loop through the targets in RA order
keys = peinfo.keys()
keys.sort()

for key in keys:
    star = peinfo[key]
    obs = obsinfo[star['name']]

    # Interpret dates
    start_year,start_month,start_day = obs['start'].split('-')
    end_year,end_month,end_day = obs['end'].split('-')
    mjd_start = sla.cldj(int(start_year), int(start_month), int(start_day))
    mjd_end = sla.cldj(int(end_year), int(end_month), int(end_day))
    if mjd_end <= mjd_start:
        print 'ERROR: end date should be after start date'
        exit(1)

    # middle used to estimate systematic uncert
    mjd_mid = (mjd_start+mjd_end)/2.

    # Compute light travel time stuff at start, middle and end of date interval
    tt,tdb,btdb_start,hutc_start,htdb,vhel,vbar = \
        sla.utc2tdb(mjd_start,longit,latit,height,star['ra'],star['dec'])

    tt,tdb,btdb_mid,hutc_mid,htdb,vhel,vbar = \
        sla.utc2tdb(mjd_mid,longit,latit,height,star['ra'],star['dec'])

    tt,tdb,btdb_end,hutc_end,htdb,vhel,vbar = \
        sla.utc2tdb(mjd_end,longit,latit,height,star['ra'],star['dec'])

    # calculate start, mid and end phases
    eph = star['ephemeris']
    if eph.time == 'HJD':
        pstart = eph.phase(hutc_start + 2400000.5)
        pmid   = eph.phase(hutc_mid + 2400000.5)
        pend   = eph.phase(hutc_end + 2400000.5)
    elif eph.time == 'HMJD':
        pstart = eph.phase(hutc_start)
        pmid   = eph.phase(hutc_mid)
        pend   = eph.phase(hutc_end)
    elif eph.time == 'BMJD':
        pstart = eph.phase(btdb_start)
        pmid   = eph.phase(btdb_mid)
        pend   = eph.phase(btdb_end)
    elif eph.time == 'BJD':
        pstart = eph.phase(btdb_start + 2400000.5)
        pmid   = eph.phase(btdb_mid + 2400000.5)
        pend   = eph.phase(btdb_end + 2400000.5)
    else:
        raise Exception('Unrecognised type of time = ' + eph.time)

    # Use to calculate effective period in terms of MJD
    period = (mjd_end-mjd_start)/(pend-pstart)

    # reference the zeropoint to just after the start, offsetting back by half the window
    # width to ensure p1 is covered.
    T0 = mjd_start + period * ((obs['p1'] - pstart) % 1) - obs['window']/(24.*60.)/2.

    # Compute prediction at mid point. Offset T0 half-way towards the actual time. This
    # leads to equal systematic errors due to light-travel time at the start, middle, and
    # end, with the start and end having the opposite sense to the middle. This should be
    # close the the minimum achievable.
    mjd_mid_pred = mjd_start + period*(pmid-pstart)
    T0 += (mjd_mid-mjd_mid_pred)/2.
    err_syst = 60.*24.*abs(mjd_mid_pred-mjd_mid)/2.

    # corresponding date
    year,month,day,hour = sla.djcl(T0)

    # Compute statistical uncertainty in predictions
    err_stat = 60.*24.*eph.etime(pmid) 

    dperiod = int(period)

    # number of exposures, where we must assume we start as early as possible. Phase interval
    # is mod(,1)
    nexp = int(math.ceil(subs.DAY*period*((obs['p2']-obs['p1']) % 1) + 30.*obs['window'])/obs['expose'])

    # Now format for output
    print '{0:15s}, {1:23s}, T0 = {2:4d}-{3:02d}-{4:02d} {5:8s}; P = {6:8d} ms [={7:1d}d {8:11s}], NxExp = {9:3d}x{10:.1f} s; Wind = {11:.1f} min; Err (stat,syst) = {12:.1f},{13:.1f} min; dates: {14:10s} to {15:10s}'.format(
        star['name'], key, year, month, day, subs.d2hms(hour,1),
        int(round(subs.DAY*1000.*period)), dperiod, subs.d2hms(24.*(period-dperiod)),
        nexp,obs['expose'],obs['window'],err_stat,err_syst,obs['start'],obs['end'])
