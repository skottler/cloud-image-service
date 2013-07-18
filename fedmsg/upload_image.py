#!/usr/bin/python

import fedmsg
import koji
import os
import shutil
import sys

def main(message):
    
    location = get_image(message)

    #Convert from qcow2 to raw
    if location.endswith('.qcow2'):
        newLocation = location[:6] + '.raw'
        os.system('qemu-img convert %s %s' % (location, (newLocation)))
        #Compress image?
        #os.system('xz -k %s' % (newLocation)) #Remove -k if do not want to keep original .raw
    else:
        newLocation = location
    #Upload to EC2
    os.system('uploader.py %s' % (newLocation))
    #fedmsg is inside uploader.py so no need to broadcast here

    #Compress image
    os.system('xz -k %s' % (newLocation)) #Remove -k if do not want to keep original .raw

    copy_image(newLocation)
    #Move to http://alt.fedoraproject.org/pub/alt/cloud

def get_image(message):
    #The message should have a koji task ID, from that we can get some data
    taskID = message
    conn = koji.ClientSession('http://koji.fedoraproject.org/kojihub')
    task = conn.getTaskInfo(taskID, request=True)
    #Download image and return location
    location = 0
    return location

def copy_image(location):
    #Copy file(s) to right location
    #TODO: Get correct location/credentials.
    """shutil.copy(newLocation, '/pub/alt/stage/19-TC2/Images/%s' % arch)"""
    #fedmsg tells that this exists
    fedmsg.publish(topic='', modname='', msg={os.path.basename(newLocation):'/pub/alt/stage/19-TC2/Images/%s' % (task['arch'])})

def update_site(location):
    """Have to work on this"""
    pass
