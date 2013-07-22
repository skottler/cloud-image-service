import fedora_ec2
import os
import subprocess
import sys 


def get_options():
    usage = """
    Removes old AMIs that are no longer needed.

    Usage: %prog [options] Region AMI-ID"""
    parser = OptionParser(usage=usage)
    parser.add_option('-t', '--time', help='Timeframe to remove?',
        default=False, action='store_true')
    global opts
    opts, args = parser.parse_args()
    if len(args) != 2:
        Script_Error("Incorrect Arguments")
    opts.region = sys.args[0]
    opts.ID = sys.args[1]
    return

def setup_log():
    """set up the main logger"""
    global mainlog
    format = logging.Formatter("[%(asctime)s %(name)s %(levelname)s]: %(message)s")
    logname = 'takedown'
    logdir = get_opt('logdir')
    if not os.path.exists(logdir):
        os.makedirs(logdir)
    if os.path.exists(os.path.join(logdir, logname + '.log')):
        os.remove(os.path.join(logdir, logname + '.log'))
    mainlog = logging.getLogger(logname)
    if get_opt('debug') == 'True':
        mainlog.setLevel(logging.DEBUG)
    else:
        mainlog.setLevel(logging.INFO)
    file_handler = logging.FileHandler(os.path.join(logdir, logname + '.log'))
    file_handler.setFormatter(format)
    mainlog.addHandler(file_handler)
    if not get_opt('quiet') == 'True':
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setFormatter(format)
        mainlog.addHandler(stdout_handler)

def take_down():
    ec2 = fedora_ec2.EC2Obj(region=opts.region, debug=get_opt('debug'),
        logfile=os.path.join(get_opt('logdir'), 'takedown-%s-%s.log' % (opts.region,opts.ID)),
        quiet=get_opt('quiet'))
    #need some sort of identifier
    destroyed = ec2.deregister_ami(opts.ID)
    return destroyed

if __name__ == '__main__':
    opts = get_options()
    setup_log()

    destroyed = take_down()
