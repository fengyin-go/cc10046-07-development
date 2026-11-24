/** 补交批次接口：待补查询、交付、回执与交付文件下载。 */
import { request } from './client'

export type BackfillBatch = {
  id: number
  批次标识: string
  来源配置: string
  采集时间: string
  原始行数: string
  有效行数: string
  存储路径: string
  压缩格式: string
  校验摘要: string
  存储状态: string
  交付状态: string
  补交单号: string
  交付时间: string
}

export type BackfillQuery = {
  source?: string
  date_from?: string
  date_to?: string
  batch?: string
  delivery_state?: 'pending' | 'delivered' | 'all'
}

export type CandidateResult = {
  items: BackfillBatch[]
  total: number
  pending: number
  delivered: number
}

export type Receipt = {
  id: number
  回执号: string
  单号: string
  批次ID: number
  批次标识: string
  来源配置: string
  采集时间: string
  原始行数: string
  有效行数: string
  存储路径: string
  校验摘要: string
  送达状态: string
  送达时间: string
}

export type Failure = {
  批次标识: string
  来源配置: string
  采集时间: string
  原因: string
}

export type DeliverResult = {
  ok: boolean
  message: string
  单号?: string
  来源配置?: string
  采集起日?: string
  采集止日?: string
  交付状态?: string
  提交批次数?: number
  实际送达批次数: number
  未送达批次数: number
  实际送达: (BackfillBatch & { 回执号?: string })[]
  未送达: Failure[]
  回执: Receipt[]
  导出?: { 任务标识: string; 目标路径: string } | null
  交付记录?: Record<string, unknown>
}

function toQuery(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return
    search.set(key, String(value))
  })
  return search.toString()
}

async function readJson<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) throw new Error(fallback)
  return (await response.json()) as T
}

export async function listSources(): Promise<string[]> {
  const payload = await readJson<{ items: string[] }>(
    await request('/api/backfill/sources'),
    '采集来源读取失败',
  )
  return payload.items
}

export async function listCandidates(query: BackfillQuery): Promise<CandidateResult> {
  return await readJson<CandidateResult>(
    await request(`/api/backfill/candidates?${toQuery(query)}`),
    '待补批次读取失败',
  )
}

export async function deliverBatches(payload: {
  source: string
  date_from: string
  date_to: string
  batch_ids: number[]
  batch_labels?: string[]
  batch?: string
  deliver_all_matching?: boolean
  operator?: string
  fail_batch_ids?: number[]
}): Promise<DeliverResult> {
  const response = await request('/api/backfill/deliver', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return await readJson<DeliverResult>(response, '补交提交失败')
}

export async function listReceipts(query: BackfillQuery & { delivery_no?: string }): Promise<Receipt[]> {
  const payload = await readJson<{ items: Receipt[] }>(
    await request(`/api/backfill/receipts?${toQuery(query)}`),
    '回执读取失败',
  )
  return payload.items
}

export async function listDeliveries(query: BackfillQuery): Promise<Record<string, unknown>[]> {
  const payload = await readJson<{ items: Record<string, unknown>[] }>(
    await request(`/api/backfill/deliveries?${toQuery(query)}`),
    '补交单读取失败',
  )
  return payload.items
}

export async function recordLateBatch(payload: {
  批次标识: string
  来源配置: string
  采集时间: string
  原始行数?: number
  有效行数?: number
}): Promise<{ ok: boolean; message: string }> {
  const response = await request('/api/backfill/record', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
  return await readJson(response, '批次登记失败')
}

export function deliveryExportUrl(deliveryId: number): string {
  return `/api/backfill/deliveries/${deliveryId}/export.csv`
}

export async function downloadDeliveryCsv(deliveryId: number, deliveryNo: string): Promise<void> {
  const response = await request(deliveryExportUrl(deliveryId))
  if (!response.ok) throw new Error('交付文件下载失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `backfill-${deliveryNo}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}
