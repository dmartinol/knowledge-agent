// Production bundle server: static assets plus a same-origin A2A proxy.
// Every proxied request is short (message/send and tasks/get), so the Route
// idle timeout never covers the agent's reasoning window.

import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import express from 'express'
import { createProxyMiddleware } from 'http-proxy-middleware'

const here = path.dirname(fileURLToPath(import.meta.url))

export function isAgentPath(requestPath) {
  return (
    requestPath === '/a2a' ||
    requestPath === '/a2a/health' ||
    requestPath.startsWith('/.well-known/')
  )
}

export function createServer({
  agentUrl = process.env.AGENT_INTERNAL_URL || 'http://127.0.0.1:8081',
  staticDir = path.join(here, 'dist'),
} = {}) {
  const app = express()
  app.disable('x-powered-by')

  app.get('/healthz', (_request, response) => {
    response.json({ status: 'ok', service: 'knowledge-agent-demo-ui' })
  })

  const proxy = createProxyMiddleware({
    target: agentUrl.replace(/\/+$/, ''),
    changeOrigin: true,
    xfwd: false,
    pathFilter: isAgentPath,
    on: {
      error: (error, _request, response) => {
        if (response && typeof response.writeHead === 'function' && !response.headersSent) {
          response.writeHead(502, { 'Content-Type': 'application/json' })
        }
        if (response && typeof response.end === 'function') {
          response.end(
            JSON.stringify({
              error: 'agent_unreachable',
              message: `The agent proxy could not reach ${agentUrl}: ${error.message}`,
            }),
          )
        }
      },
    },
  })
  app.use(proxy)

  const indexFile = path.join(staticDir, 'index.html')
  app.use(express.static(staticDir, { index: 'index.html' }))
  app.get('*', (_request, response) => {
    if (!existsSync(indexFile)) {
      response
        .status(404)
        .type('text/plain')
        .send('The UI bundle is missing. Run "npm run build" first.')
      return
    }
    response.sendFile(indexFile)
  })

  return app
}

const isEntrypoint = process.argv[1] === fileURLToPath(import.meta.url)
if (isEntrypoint) {
  const port = Number(process.env.PORT || 8080)
  const host = process.env.HOST || '0.0.0.0'
  const app = createServer()
  app.listen(port, host, () => {
    console.log(`demo UI listening on http://${host}:${port}`)
  })
}
