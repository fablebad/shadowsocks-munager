import logging

from tornado import gen
from tornado.httpclient import AsyncHTTPClient, HTTPError
from tornado.ioloop import IOLoop, PeriodicCallback

from Munager.MuAPI import MuAPI
from Munager.SSManager import SSManager
from Munager.SpeedTestManager import speedtest_thread

class Munager:
    def __init__(self, config):
        self.config = config

        # set logger
        self.logger = logging.getLogger()
        self.alive_count = 0

        # mix
        self.ioloop = IOLoop.current()
        self.mu_api = MuAPI(self.config)
        self.ss_manager = SSManager(self.config)
        self.logger.info('Munager initializing.')
    @gen.coroutine
    def upload_serverload(self):
        # update online users count
        try:
            uptime = self._uptime()
            load = self._load()
            result = yield self.mu_api.upload_systemload(uptime,load)
            if result:
                self.logger.info('upload_system load success. uptime {}, load {}'.format(uptime,load))
        except HTTPError:
            self.logger.warning('upload_system load failed')

    @gen.coroutine
    def upload_speedtest(self):
        # update online users count
        try:
            speedtest_result = speedtest_thread()
            result = yield self.mu_api.upload_speedtest(speedtest_result)
            if result:
                self.logger.info('Successfully upload speet test result {}.'.format(speedtest_result))
        except HTTPError:
            self.logger.warning('failed to upload online user count.')
    @gen.coroutine
    def update_ss_manager(self):
        # get from MuAPI and ss-manager
        users = yield self.mu_api.get_users('port')
        state = self.ss_manager.state
        self.logger.info('get MuAPI and ss-manager succeed, now begin to check ports.')
        #self.logger.debug('get state from ss-manager: {}.'.format(state))

        # remove port
        for port in state:
            if port not in users or not users.get(port).available:
                self.ss_manager.remove(port)
                self.logger.info('remove port: {}.'.format(port))

        # add port
        for port, user in users.items():
            user_id = user.id
            if user.available and port not in state:
                if self.ss_manager.add(
                        user_id=user_id,
                        port=user.port,
                        password=user.passwd,
                        method=user.method,
                        plugin=user.plugin,
                        plugin_opts=user.plugin_opts,
                ):
                    self.logger.info('add user at port: {}.'.format(user.port))

            if user.available and port in state:
                if user.passwd != state.get(port).get('password') or \
                                user.method != state.get(port).get('method'):
                    if self.ss_manager.remove(user.port) and self.ss_manager.add(
                            user_id=user_id,
                            port=user.port,
                            password=user.passwd,
                            method=user.method,
                            plugin=user.plugin,
                            plugin_opts=user.plugin_opts,
                    ):
                        self.logger.info('reset port {} due to method or password changed.'.format(user.port))
        # check finish
        self.logger.info('check ports finished.')

    @gen.coroutine
    def upload_throughput(self):
        state = self.ss_manager.state
        for port, info in state.items():
            cursor = info.get('cursor')
            throughput = info.get('throughput')
            if throughput < cursor:
                self.logger.warning('error throughput, try fix.')
                self.ss_manager.set_cursor(port, throughput)
            elif throughput > cursor:
                dif = throughput - cursor
                user_id = info.get('user_id')
                try:
                    result = yield self.mu_api.upload_throughput(user_id, dif)
                    if result:
                        self.ss_manager.set_cursor(port, throughput)
                        self.logger.info('update traffic: {} for port: {}.'.format(dif, port))
                except:
                    self.logger.info('update trafic faileds')

    @gen.coroutine
    def upload_alive_ip(self):
        state = self.ss_manager.state

        for port, info in state.items():
            user_id = info.get('user_id')
            IPs = self._get_alive_ip(port)
            cursor = info.get('cursor')
            throughput = info.get('throughput')
            if (throughput > cursor):
                self.alive_count = 5
            else:
                self.alive_count -= 1

            if (len(IPs) >= 1 and self.alive_count > 0):
                try:
                    result = yield self.mu_api.post_online_alive_ip(user_id, IPs)
                    if result:
                        self.logger.info('update port:{} alive ip: {}.'.format(port, IPs).replace("\n", ""))
                except:
                    self.logger.info('update alive ip faileds')

    @staticmethod
    def _second_to_msecond(period):
        # s to ms
        return period * 1000

    @staticmethod
    def _uptime():
        with open('/proc/uptime', 'r') as f:
            return float(f.readline().split()[0])

    @staticmethod
    def _get_alive_ip(port):
        import os
        return os.popen(
            "netstat -anp | grep {:d} | grep ESTABLISHED | awk '{{print $5}}' | awk -F \":\" '{{print $1}}' | sort -u".format(port)).readlines()

    @staticmethod
    def _load():
        import os
        return os.popen(
            "cat /proc/loadavg | awk '{ print $1\" \"$2\" \"$3 }'").readlines()[0]
    def run(self):
        # period task
        PeriodicCallback(
            callback=self.update_ss_manager,
            callback_time=self._second_to_msecond(self.config.get('update_port_period', 60)),
            io_loop=self.ioloop,
        ).start()
        PeriodicCallback(
            callback=self.upload_throughput,
            callback_time=self._second_to_msecond(self.config.get('upload_throughput_period', 600)),
            io_loop=self.ioloop,
        ).start()

        PeriodicCallback(
            callback=self.upload_alive_ip,
            callback_time=self._second_to_msecond(self.config.get('upload_throughput_period', 480)),
            io_loop=self.ioloop,
        ).start()
        PeriodicCallback(
            callback=self.upload_serverload,
            callback_time=self._second_to_msecond(self.config.get("upload_serverload_period",60)),
            io_loop = self.ioloop,
        ).start()
        '''
        PeriodicCallback(
            callback_time=self._second_to_msecond(self.config.get("upload_speedtest_period",21600)),
            callback=self.upload_speedtest,
            io_loop=self.ioloop
        ).start()
        '''
        try:
            # Init task
            self.ioloop.run_sync(self.update_ss_manager)
            self.ioloop.start()
        except KeyboardInterrupt:
            del self.mu_api
            del self.ss_manager
            print('Bye~')



