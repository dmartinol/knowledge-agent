import { mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'

import express from 'express'
import request from 'supertest'
import { afterEach, describe, expect, it } from 'vitest'

import { createServer, isAgentPath } from '../server.mjs'

const servers = []

function listen(app) {
  return new Promise((resolve) => {
    const server = app.listen(0, '127.0.0.1', () => resolve(server))
    servers.push(server)
  })
}

function baseUrl(server) {
  return `http://127.0.0.1:${server.address().port}`
}

afterEach(async () => {
  await Promise.all(
    servers.splice(0).map(
      (server) => new Promise((resolve) => server.close(resolve)),
    ),
  )
})

async function startAgentStub() {
  const app = express()
  app.use(express.json())
  app.all('*', (req, res) => {
    res.json({
      method: req.method,
      url: req.originalUrl,
      contentType: req.headers['content-type'],
      body: req.body,
    })
  })
  const server = await listen(app)
  return baseUrl(server)
}

function staticDirWithIndex() {
  const dir = mkdtempSync(path.join(tmpdir(), 'ka-ui-'))
  writeFileSync(path.join(dir, 'index.html'), '<div id="root">shell</div>')
  return dir
}

describe('isAgentPath', () => {
  it('proxies only the A2A surface', () => {
    expect(isAgentPath('/a2a')).toBe(true)
    expect(isAgentPath('/a2a/health')).toBe(true)
    expect(isAgentPath('/.well-known/agent-card.json')).toBe(true)
    expect(isAgentPath('/healthz')).toBe(false)
    expect(isAgentPath('/assets/index.js')).toBe(false)
  })
})

describe('demo UI server', () => {
  it('proxies message/send to the agent with the path and body intact', async () => {
    const agentUrl = await startAgentStub()
    const app = createServer({ agentUrl, staticDir: staticDirWithIndex() })
    const payload = { jsonrpc: '2.0', id: 'ui-1', method: 'message/send', params: { message: {} } }

    const response = await request(app).post('/a2a').send(payload)

    expect(response.status).toBe(200)
    expect(response.body).toMatchObject({
      method: 'POST',
      url: '/a2a',
      contentType: expect.stringContaining('application/json'),
      body: payload,
    })
  })

  it('proxies the agent card and agent health endpoints', async () => {
    const agentUrl = await startAgentStub()
    const app = createServer({ agentUrl, staticDir: staticDirWithIndex() })

    const card = await request(app).get('/.well-known/agent-card.json?fresh=1')
    const health = await request(app).get('/a2a/health')

    expect(card.body.url).toBe('/.well-known/agent-card.json?fresh=1')
    expect(health.body.url).toBe('/a2a/health')
  })

  it('answers its own health probe without touching the agent', async () => {
    const app = createServer({
      agentUrl: 'http://127.0.0.1:1',
      staticDir: staticDirWithIndex(),
    })

    const response = await request(app).get('/healthz')

    expect(response.status).toBe(200)
    expect(response.body).toEqual({
      status: 'ok',
      service: 'knowledge-agent-demo-ui',
    })
  })

  it('serves the built bundle and falls back to index.html', async () => {
    const app = createServer({
      agentUrl: 'http://127.0.0.1:1',
      staticDir: staticDirWithIndex(),
    })

    const response = await request(app).get('/runs/run-1')

    expect(response.status).toBe(200)
    expect(response.text).toContain('shell')
  })

  it('explains a missing bundle instead of failing with a stack trace', async () => {
    const app = createServer({
      agentUrl: 'http://127.0.0.1:1',
      staticDir: path.join(tmpdir(), 'ka-ui-missing-dist'),
    })

    const response = await request(app).get('/')

    expect(response.status).toBe(404)
    expect(response.text).toContain('npm run build')
  })

  it('returns a JSON 502 when the agent is unreachable', async () => {
    const app = createServer({
      agentUrl: 'http://127.0.0.1:1',
      staticDir: staticDirWithIndex(),
    })

    const response = await request(app)
      .post('/a2a')
      .send({ jsonrpc: '2.0', id: 'ui-2', method: 'message/send', params: {} })

    expect(response.status).toBe(502)
    expect(response.body.error).toBe('agent_unreachable')
  })
})
