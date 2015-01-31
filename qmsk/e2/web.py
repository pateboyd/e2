import asyncio
import aiohttp.wsgi
import logging; log = logging.getLogger('qmsk.e2.web')
import qmsk.e2.client
import qmsk.e2.server
import qmsk.web.async
import qmsk.web.html
import qmsk.web.json
import qmsk.web.urls
import werkzeug
import werkzeug.exceptions

html = qmsk.web.html.html5

WEB_PORT = 8081
STATIC = './static'

class Index(qmsk.web.async.Handler):
    CLIENT = '/static/client/e2.html'

    def process(self):
        return werkzeug.redirect(self.CLIENT)

class PresetMixin:
    """
        preset: Preset              activated preset, or requested preset, or active preset
        transition: True or int     activated transition
        seq: float                  current sequence number
    """

    def init(self):
        self.preset = None
        self.transition = self.error = None
        self.seq = self.app.server.seq

    @asyncio.coroutine
    def process_preset(self, preset=None, post=None):
        """
            Raises werkzeug.exceptions.HTTPException.
        """

        if preset:
            try:
                preset = self.app.presets[preset]
            except KeyError as error:
                raise werkzeug.exceptions.BadRequest("Invalid preset={preset}".format(preset=preset))
        else:
            preset = None

        if post is not None:
            try:
                self.preset, self.transition, self.seq = yield from self.app.process(preset, post)
            except qmsk.e2.server.SequenceError as error:
                raise werkzeug.exceptions.BadRequest(error)
            except qmsk.e2.client.Error as error:
                raise werkzeug.exceptions.InternalServerError(error)
            except qmsk.e2.server.Error as error:
                raise werkzeug.exceptions.InternalServerError(error)
        elif preset:
            self.preset = preset
        else:
            self.preset = self.app.presets.active

class HTMLBase(qmsk.web.html.HTMLMixin, qmsk.web.async.Handler):
    TITLE = "Encore2 Control"

    CSS = (
        '/static/lib/bootstrap.min.css',
        '/static/lib/bootstrap-theme.min.css',

        '/static/client/app.css',
    )

    JS = (
        '/static/lib/jquery-1.11.2.min.js',
        '/static/lib/bootstrap.min.js',
    )

    HEAD = (
        html.meta(name="viewport", content="width=device-width, initial-scale=1"),
    )

    def status(self):
        if self.error:
            return self.error.code
        else:
            return 200

    def render_header(self):
        return html.div(id='header', class_='navbar')(
            html.div(class_='navbar-header')(
                html.a(href=self.url(Index), class_='navbar-brand')(self.TITLE),
            ),
            html.div(class_='narbar-collapse')(
                html.ul(class_='nav navbar-nav')(
                    html.li(class_=('active' if isinstance(self, page) else None))(
                        html.a(href=self.url(page))(page.PAGE_TITLE)
                    ) for page in HTML_PAGES
                ),
            ),
        )

    def render_status(self):
        return [ ]

    def render_content(self):
        raise NotImplementedError()

    def render(self):
        status = []

        for msg in self.render_status():
            status.append(html.p(msg))

        return html.div(class_='container-fluid', id='container')(
            self.render_header(),
            self.render_content(),
            html.div(id='status')(
                status or html.p("Ready")
            ),
        )

class HTMLPresets(PresetMixin, HTMLBase):
    PAGE_TITLE = "Presets"

    def init(self):
        super().init()
        self.error = None
        self.presets = self.app.presets

    @asyncio.coroutine
    def process_async(self):
        try:
            preset = self.request.form.get('preset', type=int)
        except ValueError as error:
            self.error = werkzeug.exceptions.BadRequest(error)
            return
        
        try:
            yield from self.process_preset(preset, self.request_post())
        except werkzeug.exceptions.HTTPException as error:
            self.error = error
            return

    def render_preset_destination(self, preset, destination):
        if preset == destination.program:
            format = "<{title}>"
        elif preset == destination.preview:
            format = "[{title}]"
        else:
            format = "({title})"

        return format.format(title=destination.title)

    def render_preset(self, preset):
        css = set(['preset'])

        log.debug("preset=%s preview=%s program=%s", preset, self.presets.preview, self.presets.program)

        for destination in preset.destinations:
            if preset == destination.preview:
                css.add('preview')
            
            if preset == destination.program:
                css.add('program')

        if preset == self.presets.active:
            css.add('active')

        return html.button(
                type    = 'submit',
                name    = 'preset',
                value   = preset.preset,
                class_  = ' '.join(css) if css else None,
                id      = 'preset-{preset}'.format(preset=preset.preset),
                title   = ' + '.join(
                    self.render_preset_destination(preset, destination) for destination in preset.destinations
                ),
        )(preset.title)

    def render_preset_group (self, group):
        if not group.presets:
            return

        return html.div(class_='preset-group')(
                html.h3(group.title) if group.title else None,
                [
                    self.render_preset(preset) for preset in group.presets
                ],
        )

    def render_status(self):
        if self.preset is not None:
            yield "Recalled preset {preset}".format(preset=self.preset)

        if self.transition is not None:
            yield "Transitioned {transition}".format(transition=self.transition)

        if self.error is not None:
            yield "{error}: {description}".format(error=self.error, description=self.error.description)

    def render_content(self):
        return html.form(action='', method='POST')(
            html.input(type='hidden', name='seq', value=self.seq),
            html.div(
                html.div(id='tools')(
                    html.button(type='submit', name='cut', value='cut', id='cut')("Cut"),
                    html.button(type='submit', name='autotrans', value='autotrans', id='autotrans')("Auto Trans"),
                ),
                html.div(id='presets', class_='presets')(
                    self.render_preset_group(group) for group in self.presets.groups
                ),
            ),
        )

class HTMLDestinations(HTMLBase):
    PAGE_TITLE = "Destinations"

    def render_destination_preset(self, preset, class_):
        css = set(['preset'])

        if preset:
            css.add(class_)
        else:
            css.add('empty')

        return html.button(class_=' '.join(css))(
            preset.title if preset else None
        )

    def render_destination(self, destination):
        return html.div(class_='destination')(
                html.h3(destination.title),
                self.render_destination_preset(destination.program, 'program'),
                self.render_destination_preset(destination.preview, 'preview'),
        )

    def render_content(self):
        return html.div(
            html.div(id='destinations', class_='presets')(
                self.render_destination(destination) for destination in self.app.presets.destinations
            ),
        )

HTML_PAGES = (
    HTMLPresets,
    HTMLDestinations,
)

class APIBase (qmsk.web.json.JSONMixin, qmsk.web.async.Handler):
    CORS_ORIGIN = '*'
    CORS_METHODS = ('GET', 'POST')
    CORS_HEADERS = ('Content-Type', 'Authorization')
    CORS_CREDENTIALS = True

    def render_preset(self, preset):
        destinations = dict()
        
        out = {
            'preset': preset.preset,
            'destinations': destinations,
            'title': preset.title,
            'group': preset.group.title if preset.group else None,
        }
       
        for destination in preset.destinations:
            if preset == destination.program:
                status = 'program'

            elif preset == destination.preview:
                status = 'preview'

            else:
                status = None

            destinations[destination.title] = status

            if status:
                out[status] = True

            if preset == self.app.presets.active:
                out['active'] = True
        
        return out

class APIIndex(APIBase):
    def init(self):
        self.presets = self.app.presets
        self.seq = self.app.server.seq

    def render_group (self, group):
        return {
                'title': group.title,
                'presets': [preset.preset for preset in group.presets],
        }

    def render_destination (self, destination):
        return {
                'outputs': destination.index,
                'title': destination.title,
                'preview': destination.preview.preset if destination.preview else None,
                'program': destination.program.preset if destination.program else None,
        }

    def render_json(self):
        return {
                'seq': self.seq,
                'presets': {preset.preset: self.render_preset(preset) for preset in self.presets},
                'groups': [self.render_group(group) for group in self.presets.groups],
                'destinations': [self.render_destination(destination) for destination in self.presets.destinations],
        }

class APIPreset(PresetMixin, APIBase):
    @asyncio.coroutine
    def process_async(self, preset=None):
        post = self.request_post()
        
        # raises HTTPException
        yield from self.process_preset(preset, post)

    def render_json(self):
        out = {
            'seq': self.seq,
        }

        if self.preset:
            out['preset'] = self.render_preset(self.preset)
        
        if self.transition is not None:
            out['transition'] = self.transition

        return out

class E2Web(qmsk.web.async.Application):
    URLS = qmsk.web.urls.rules({
        '/':                            Index,
        '/presets':                     HTMLPresets,
        '/destinations':                HTMLDestinations,
        '/api/v1/':                     APIIndex,
        '/api/v1/preset/':              APIPreset,
        '/api/v1/preset/<int:preset>':  APIPreset,
    })

    def __init__ (self, server, presets):
        """
            server: qmsk.e2.server.Server
            presets: qmsk.e2.presets.E2Presets
        """
        super().__init__()
        
        self.server = server
        self.presets = presets

    @asyncio.coroutine
    def process(self, preset, params):
        """
            Process an action request

            preset: Preset
            params: {
                cut: *
                autotrans: *
                transition: int
                seq: float or None
            }
        

            Raises qmsk.e2.client.Error, qmsk.e2.server.Error
        """

        if 'seq' in params:
            seq = float(params['seq'])
        else:
            seq = None

        if 'cut' in params:
            transition = 0
        elif 'autotrans' in params:
            transition = True
        elif 'transition' in params:
            transition = int(params['transition'])
        else:
            transition = None 

        active, seq = yield from self.server.activate(preset, transition, seq)
            
        return active, transition, seq

import argparse

def parser (parser):
    group = parser.add_argument_group("qmsk.e2.web Options")
    group.add_argument('--e2-web-listen', metavar='ADDR',
        help="Web server listen address")
    group.add_argument('--e2-web-port', metavar='PORT', type=int, default=WEB_PORT,
        help="Web server port")
    group.add_argument('--e2-web-static', metavar='PATH', default=STATIC,
        help="Web server /static path")

@asyncio.coroutine
def apply (args, server, loop):
    """
        server: qmsk.e2.server.Server
    """

    application = E2Web(server, server.presets)

    if args.e2_web_static:
        application = werkzeug.wsgi.SharedDataMiddleware(application, {
            '/static':  args.e2_web_static,
        })

    def server_factory():
        return aiohttp.wsgi.WSGIServerHttpProtocol(application,
                readpayload = True,
                debug       = True,
        )

    server = yield from loop.create_server(server_factory,
            host    = args.e2_web_listen,
            port    = args.e2_web_port,
    )

    return application

