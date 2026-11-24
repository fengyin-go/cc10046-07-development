<template>
  <section class="page" data-testid="backfill-page">
    <header class="page-head">
      <div>
        <h2>补交批次</h2>
        <p class="page-desc">
          按采集来源与采集日检索可重发批次结果集，只交付实际选中的批次，回执可逐批复核。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" data-testid="refresh" type="button" @click="reload">重新查询</button>
        <button
          class="btn"
          data-testid="deliver-all"
          type="button"
          :disabled="!counts.pending || submitting"
          @click="submitDelivery(true)"
        >
          按条件全量交付
        </button>
        <button
          class="btn primary"
          data-testid="submit-delivery"
          type="button"
          :disabled="!selectedIds.length || submitting"
          @click="submitDelivery(false)"
        >
          {{ submitting ? '提交中…' : `提交补交（${selectedIds.length}）` }}
        </button>
      </div>
    </header>

    <form class="filter-bar" data-testid="backfill-filters" @submit.prevent="reload">
      <label class="filter-item">
        <span>采集来源</span>
        <select v-model="query.source" data-testid="filter-source">
          <option value="">全部来源</option>
          <option v-for="source in sources" :key="source" :value="source">{{ source }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>采集起日</span>
        <input v-model="query.date_from" type="date" data-testid="filter-date-from" />
      </label>
      <label class="filter-item">
        <span>采集止日</span>
        <input v-model="query.date_to" type="date" data-testid="filter-date-to" />
      </label>
      <label class="filter-item">
        <span>批次标签</span>
        <input v-model="query.batch" data-testid="filter-batch" placeholder="按完整批次标签检索" />
      </label>
      <label class="filter-item">
        <span>交付状态</span>
        <select v-model="query.delivery_state" data-testid="filter-state">
          <option value="pending">仅待补</option>
          <option value="delivered">仅已交付</option>
          <option value="all">全部</option>
        </select>
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <p class="status-legend" data-testid="query-summary">
      <span class="legend-item">当前结果：{{ total }} 批</span>
      <span class="legend-item">待补：{{ counts.pending }}</span>
      <span class="legend-item">已交付：{{ counts.delivered }}</span>
      <span class="legend-item">已选：{{ selectedIds.length }}</span>
      <span v-if="query.source" class="legend-item">来源：{{ query.source }}</span>
      <span v-if="query.date_from || query.date_to" class="legend-item">
        采集日：{{ query.date_from || '不限' }} ~ {{ query.date_to || '不限' }}
      </span>
    </p>

    <table class="data-table" data-testid="candidate-table">
      <thead>
        <tr>
          <th>选择</th>
          <th>批次标识</th>
          <th>来源配置</th>
          <th>采集时间</th>
          <th>原始行数</th>
          <th>有效行数</th>
          <th>校验摘要</th>
          <th>交付状态</th>
          <th>补交单号</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="row.id"
          :data-testid="`candidate-${row.id}`"
          :data-batch="row.批次标识"
          :data-state="row.交付状态"
        >
          <td>
            <input
              v-model="selectedIds"
              type="checkbox"
              :value="row.id"
              :disabled="row.交付状态 === '已交付'"
              :data-testid="`select-${row.id}`"
            />
          </td>
          <td>{{ row.批次标识 }}</td>
          <td>{{ row.来源配置 }}</td>
          <td>{{ row.采集时间 }}</td>
          <td>{{ row.原始行数 }}</td>
          <td>{{ row.有效行数 }}</td>
          <td>{{ row.校验摘要 }}</td>
          <td>{{ row.交付状态 }}</td>
          <td>{{ row.补交单号 || '—' }}</td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="9" class="empty-state">当前条件下没有可重发批次</td>
        </tr>
      </tbody>
    </table>

    <section v-if="result" class="result-block" data-testid="delivery-result">
      <h3 class="result-title">
        本次提交结果：{{ result.message }}
      </h3>
      <p class="status-legend">
        <span class="legend-item">单号：{{ result.单号 || '—' }}</span>
        <span class="legend-item">实际送达：{{ result.实际送达批次数 }} 批</span>
        <span class="legend-item">未送达：{{ result.未送达批次数 }} 批</span>
        <span class="legend-item">交付状态：{{ result.交付状态 || '—' }}</span>
      </p>

      <table class="data-table" data-testid="receipt-table">
        <thead>
          <tr>
            <th>回执号</th>
            <th>批次标识</th>
            <th>来源配置</th>
            <th>采集时间</th>
            <th>送达状态</th>
            <th>送达时间</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="receipt in result.回执"
            :key="receipt.回执号"
            :data-testid="`receipt-${receipt.回执号}`"
          >
            <td>{{ receipt.回执号 }}</td>
            <td>{{ receipt.批次标识 }}</td>
            <td>{{ receipt.来源配置 }}</td>
            <td>{{ receipt.采集时间 }}</td>
            <td>{{ receipt.送达状态 }}</td>
            <td>{{ receipt.送达时间 }}</td>
          </tr>
          <tr v-if="!result.回执.length">
            <td colspan="6" class="empty-state">本次没有送出批次，无回执</td>
          </tr>
        </tbody>
      </table>

      <table v-if="result.未送达.length" class="data-table" data-testid="failure-table">
        <thead>
          <tr><th>批次标识</th><th>来源配置</th><th>采集时间</th><th>未送达原因</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in result.未送达" :key="`${item.批次标识}-${item.原因}`">
            <td>{{ item.批次标识 }}</td>
            <td>{{ item.来源配置 || '—' }}</td>
            <td>{{ item.采集时间 || '—' }}</td>
            <td>{{ item.原因 }}</td>
          </tr>
        </tbody>
      </table>

      <div class="page-actions">
        <button
          v-if="deliveryId"
          class="btn"
          data-testid="download-delivery"
          type="button"
          @click="downloadDelivery"
        >
          下载本次交付文件
        </button>
        <button class="btn ghost" data-testid="save-receipts" type="button" @click="saveReceipts">
          保存回执清单
        </button>
      </div>
    </section>

    <section class="result-block" data-testid="receipt-history">
      <h3 class="result-title">按原查询回看回执</h3>
      <p class="page-desc">回执按实际送出的来源与采集日归档，可按上面同一组条件回查。</p>
      <table class="data-table">
        <thead>
          <tr><th>回执号</th><th>单号</th><th>批次标识</th><th>来源配置</th><th>采集时间</th><th>送达时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="receipt in receipts" :key="receipt.回执号" :data-testid="`history-${receipt.回执号}`">
            <td>{{ receipt.回执号 }}</td>
            <td>{{ receipt.单号 }}</td>
            <td>{{ receipt.批次标识 }}</td>
            <td>{{ receipt.来源配置 }}</td>
            <td>{{ receipt.采集时间 }}</td>
            <td>{{ receipt.送达时间 }}</td>
          </tr>
          <tr v-if="!receipts.length">
            <td colspan="6" class="empty-state">当前条件下没有回执</td>
          </tr>
        </tbody>
      </table>

      <details class="late-batch">
        <summary>登记迟到的结果批次（演练）</summary>
        <form class="filter-bar" data-testid="late-batch-form" @submit.prevent="submitLateBatch">
          <label class="filter-item">
            <span>批次标识</span>
            <input v-model="lateBatch.批次标识" required data-testid="late-batch-label" />
          </label>
          <label class="filter-item">
            <span>来源配置</span>
            <input v-model="lateBatch.来源配置" required data-testid="late-batch-source" />
          </label>
          <label class="filter-item">
            <span>采集时间</span>
            <input v-model="lateBatch.采集时间" type="date" required data-testid="late-batch-date" />
          </label>
          <button class="btn" data-testid="late-batch-submit" type="submit">登记批次</button>
        </form>
        <p v-if="lateMessage" class="page-desc" data-testid="late-batch-message">{{ lateMessage }}</p>
      </details>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 批可重发结果</span>
      <span v-if="errorMessage" class="error-text" data-testid="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import {
  downloadDeliveryCsv,
  deliverBatches,
  listCandidates,
  listReceipts,
  listSources,
  recordLateBatch,
} from '@/api/backfill'
import type { BackfillBatch, DeliverResult, Receipt } from '@/api/backfill'

const emptyQuery = () => ({
  source: '',
  date_from: '',
  date_to: '',
  batch: '',
  delivery_state: 'pending' as 'pending' | 'delivered' | 'all',
})

const query = reactive(emptyQuery())
const sources = ref<string[]>([])
const rows = ref<BackfillBatch[]>([])
const receipts = ref<Receipt[]>([])
const total = ref(0)
const counts = reactive({ pending: 0, delivered: 0 })
const selectedIds = ref<number[]>([])
const submitting = ref(false)
const result = ref<DeliverResult | null>(null)
const deliveryId = ref<number | null>(null)
const errorMessage = ref('')
const lateMessage = ref('')
const lateBatch = reactive({ 批次标识: '', 来源配置: '', 采集时间: '' })

function parameters() {
  return {
    source: query.source || undefined,
    date_from: query.date_from || undefined,
    date_to: query.date_to || undefined,
    batch: query.batch || undefined,
    delivery_state: query.delivery_state,
  }
}

function resetFilters() {
  Object.assign(query, emptyQuery())
  selectedIds.value = []
  void reload()
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listCandidates(parameters())
    rows.value = payload.items
    total.value = payload.total
    counts.pending = payload.pending
    counts.delivered = payload.delivered
    // 只保留仍在当前结果集中、且仍待补的选择。
    const visible = new Set(
      payload.items.filter((item) => item.交付状态 !== '已交付').map((item) => item.id),
    )
    selectedIds.value = selectedIds.value.filter((id) => visible.has(id))
    await loadReceipts()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '待补批次读取失败'
  }
}

async function loadReceipts() {
  try {
    receipts.value = await listReceipts(parameters())
  } catch {
    receipts.value = []
  }
}

async function submitDelivery(deliverAll: boolean) {
  if (!deliverAll && !selectedIds.value.length) return
  submitting.value = true
  errorMessage.value = ''
  try {
    // 全量交付由服务端按当前来源 + 采集日窗口重新取待补集合；
    // 勾选交付只送选中的批次ID，查询后才到的批次留在下一轮清单里。
    const payload = await deliverBatches({
      source: query.source,
      date_from: query.date_from,
      date_to: query.date_to,
      batch_ids: deliverAll ? [] : [...selectedIds.value],
      deliver_all_matching: deliverAll,
      batch: query.batch || undefined,
      operator: '数据工程组值班员',
    })
    result.value = payload
    deliveryId.value = payload.交付记录 ? Number(payload.交付记录.id) : null
    if (!payload.ok && !payload.回执.length) {
      errorMessage.value = payload.message
    }
    selectedIds.value = []
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '补交提交失败'
  } finally {
    submitting.value = false
  }
}

function saveReceipts() {
  if (!result.value?.回执.length) return
  const headers = ['回执号', '单号', '批次标识', '来源配置', '采集时间', '送达状态', '送达时间']
  const lines = [headers.join(',')]
  for (const receipt of result.value.回执) {
    lines.push(headers.map((key) => JSON.stringify(String(receipt[key as keyof Receipt] ?? ''))).join(','))
  }
  const blob = new Blob([`${lines.join('\n')}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `receipts-${result.value.单号 ?? 'backfill'}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

async function downloadDelivery() {
  if (!deliveryId.value) return
  errorMessage.value = ''
  try {
    await downloadDeliveryCsv(deliveryId.value, String(result.value?.单号 ?? 'backfill'))
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '交付文件下载失败'
  }
}

async function submitLateBatch() {
  lateMessage.value = ''
  try {
    const payload = await recordLateBatch({
      批次标识: lateBatch.批次标识,
      来源配置: lateBatch.来源配置,
      采集时间: lateBatch.采集时间,
    })
    lateMessage.value = payload.message
    if (payload.ok) {
      lateBatch.批次标识 = ''
      lateBatch.采集时间 = ''
      await reload()
    }
  } catch (error) {
    lateMessage.value = error instanceof Error ? error.message : '批次登记失败'
  }
}

onMounted(async () => {
  try {
    sources.value = await listSources()
  } catch {
    sources.value = []
  }
  await reload()
})
</script>
