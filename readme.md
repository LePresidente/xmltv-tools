#TMDB and TVDB xmltv enhancement for New Zealand
This is something of a proof of concept at this stage, but it should be error free. I'll keep it updated as I fine tune it.

I intend (have started) to write a new xmltv grabber that uses mhegepgsnoop data enhanced with goodness from the web. That's the end game. For now you'll have to make do with `xmltv-proc-nz`

I found [`xmltv-proc-nz`](https://github.com/hadleyrich/xmltv-tools/blob/master/xmltv-proc-nz), written by Hads, but it's bit out of date. What this does is tidy up the guide data a bit and augment it with matching stuff from http://www.themoviedb.org/ and http://thetvdb.com. I do not know the background of how this came to be, but it required some custom data hosted online and the movie database API was out of date. I've hacked it to work with Python 3, and it seems to do a good job, but you will need to install the ported Python APIs for TMDB and TVDB from:

 - https://github.com/apelly/tvdb_api
 - https://github.com/apelly/pytmdb3

I will continue to tidy it up and enhance it over the coming months, but it appears functional right now.

##Summary
`xmltv-proc-nz`
An enhancement of Hads original, comprehensive work.

##Setup
It looks for `xmltv-proc-nz.xml` in `~/.xmltv`

There is help text in the sample config, and it should be quite obvious how to work it.
You will need to get API keys from TVDB and TMDB and stick them in `~/.xmltv/xmltv-proc-nz.xml` They want a lot of information from you, but approval appears to be automatic.

##Background
This is part of an attempt to bring some coherency to the quagmire that is New Zealand xmltv listing information. Setting up MythTV already makes for a busy time, as you know, and initially I didn't really bother looking into anything trickier than strictly necessary.

I've been using MythTV as my exclusive TV for a bit now, and slowly working through my personal list of paper cuts. Now it's time to address this whole guide data thing.

In the beginning I was using Hads' script [tv_grab_nz-py](http://nice.net.nz/scripts/tv_grab_nz-py). I don't know how I found this originally. Probably on the MythTV wiki. Anyway, that script grabs the guide data from http://epg.org.nz/freeview.xml.gz, loops through it, and drops anything for channels that aren't in your `~/.xmltv/tv_grab_nz-py.conf` file.

That method provides sparse but functional guide data. Thanks Hads! It's also a good option for people who only have satellite; I understand that the DVB-T mheg data is as good as it gets in NZ.

##Progress
Due to a tip off on the MythTV NZ mailing list I took a look at [mhegsnoop](http://sourceforge.net/projects/mhegepgsnooppy) by David Moore and Bruce Wilson. This is clever. It sniffs the guide data from your DVB-T stream. Some of the default options are a bit odd, but this command line works for me:

`./mhegepgsnoop-0.6.0.py -c -v -p -o xmltv.xml`

In a nutshell, what this does is listen for and decode the mheg stream then throw away data for channels you don't have configured in MythTV. It pretty much just worked for me, so I didn’t bother wondering too much about how it was doing it. 

The default adaptor is `/dev/dvb/adapter1/demux0` which works for me.

>I have failed to get mhegepgsnoop to tune to a channel. At this stage I don't know if you *have* to get it to tune a channel (`-t`); it was able to get data from a tuner that was in use, and one unused, but I'm not sure if that was because the unused one was still tuned from before.

There appears to be a bug when passing mysql options to the script. At first I edited the script to use defaults appropriate for me. When I went back to try and make it a bit more elegant I noticed the `-p` option. This uses the MythTV Python module for database access. Very nice.

The `-c` option removes "All New " from the beginning of show names, but there seems to be a minor bug that shows up when you don't have the option. I haven't bothered to change the script; that'll just give me a maintenance issue in the future. It works well.

That addresses an issue with some missing channel data from [epg.org.nz](http://epg.org.nz), but the information provided is still pretty thin on the ground.

##ToDo:
* Remove the live lotto drawing show. It always breaks a movie in two.
* Experiment with `tv_extractinfo_en` which I just discovered. From package `xmltv-util`. Someone went to a lot of effort to pretty up their guide data!



