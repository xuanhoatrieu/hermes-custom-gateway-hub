/**
 * Custom Gateway Hub — Hermes Desktop Runtime Plugin
 * Location: <HERMES_HOME>/desktop-plugins/custom-gateway-hub/plugin.js
 *
 * Update-safe user-space plugin:
 *  - Auto-loads or manually probes `{base_url}/models` ("Check Connection & Tải Model mới")
 *  - Separates Content/Chat models vs Image Generation models automatically
 *  - Lets the user pick & apply Content Model + Image Model + PPT-Master sync in one click
 *  - Syncs live chat session + composer model menu immediately
 */

import {
  Badge,
  Button,
  Codicon,
  Input,
  PALETTE_AREA,
  ROUTES_AREA,
  RowButton,
  ScrollArea,
  SIDEBAR_NAV_AREA,
  STATUSBAR_AREAS,
  StatusDot,
  Switch,
  Tip,
  cn,
  haptic,
  host,
  isSubmitEnter,
  queryClient,
  useMutation,
  usePluginI18n,
  useQuery,
  useQueryClient,
  useValue
} from '@hermes/plugin-sdk'
import { useEffect, useMemo, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'custom-gateway-hub'
const ROUTE_PATH = '/gateway-hub'
const QUERY_KEY = ['plugin', ID, 'state']
const AUTO_CHECK_COOLDOWN_MS = 60_000

let lastAutoCheckAt = 0

const MESSAGES = {
  en: {
    navLabel: 'Gateway Models',
    pageTitle: 'Custom Gateway Model Hub',
    pageSubtitle:
      'Kiểm tra kết nối Custom Endpoint, tự động tải danh sách model mới (/v1/models) và chọn riêng Model Sinh Nội Dung & Model Tạo Ảnh.',
    checkBtn: 'Check Connection & Tải Model mới',
    checkingBtn: 'Đang kiểm tra...',
    saveBtn: 'Lưu & Áp dụng ngay',
    savingBtn: 'Đang lưu...',
    savedLabel: 'Đã đồng bộ',
    endpointConfig: 'Cấu hình Endpoint & API Key',
    autoCheckLabel: 'Tự động tải model mới khi mở trang',
    pptSyncLabel: 'Đồng bộ Model Ảnh sang PPT-Master (.env)',
    contentCardTitle: 'Model Sinh Nội Dung (Chat / Reasoning)',
    contentCardSub: 'Dùng cho hội thoại chính, lập trình, viết kịch bản và suy luận',
    imageCardTitle: 'Model Tạo Ảnh (Image Generation)',
    imageCardSub: 'Dùng cho công cụ image_generate, chỉnh sửa ảnh và minh họa slide',
    searchChatPlaceholder: 'Tìm model sinh nội dung (gpt-6, claude, gemini...)',
    searchImagePlaceholder: 'Tìm model tạo ảnh (gpt-image, gemini...)',
    customModelPlaceholder: 'Hoặc nhập mã model tùy chỉnh rồi nhấn Enter...',
    useCustomBtn: 'Chọn',
    activeBadge: 'Đang dùng',
    selectedBadge: 'Sẽ áp dụng',
    newBadge: 'MỚI',
    allFamilies: 'Tất cả',
    statusChipTip: img => `Gateway Image Model: ${img} — Nhấn để mở bảng chọn Model Chat & Ảnh`,
    checkSuccessToast: (chatCount, imgCount, newCount, ms) =>
      newCount > 0
        ? `Kết nối thành công (${ms} ms): ${chatCount} model nội dung, ${imgCount} model ảnh (+${newCount} model mới!)`
        : `Kết nối ổn định (${ms} ms): ${chatCount} model nội dung, ${imgCount} model ảnh.`,
    applySuccessToast: (chatModel, imgModel) =>
      `Đã áp dụng: Nội dung [${chatModel}] • Tạo ảnh [${imgModel}]`
  },
  vi: {
    navLabel: 'Gateway Models',
    pageTitle: 'Custom Gateway Model Hub',
    pageSubtitle:
      'Kiểm tra kết nối Custom Endpoint, tự động tải danh sách model mới (/v1/models) và chọn riêng Model Sinh Nội Dung & Model Tạo Ảnh.',
    checkBtn: 'Check Connection & Tải Model mới',
    checkingBtn: 'Đang kiểm tra...',
    saveBtn: 'Lưu & Áp dụng ngay',
    savingBtn: 'Đang lưu...',
    savedLabel: 'Đã đồng bộ',
    endpointConfig: 'Cấu hình Endpoint & API Key',
    autoCheckLabel: 'Tự động tải model mới khi mở trang',
    pptSyncLabel: 'Đồng bộ Model Ảnh sang PPT-Master (.env)',
    contentCardTitle: 'Model Sinh Nội Dung (Chat / Reasoning)',
    contentCardSub: 'Dùng cho hội thoại chính, lập trình, viết kịch bản và suy luận',
    imageCardTitle: 'Model Tạo Ảnh (Image Generation)',
    imageCardSub: 'Dùng cho công cụ image_generate, chỉnh sửa ảnh và minh họa slide',
    searchChatPlaceholder: 'Tìm model sinh nội dung (gpt-6, claude, gemini...)',
    searchImagePlaceholder: 'Tìm model tạo ảnh (gpt-image, gemini...)',
    customModelPlaceholder: 'Hoặc nhập mã model tùy chỉnh rồi nhấn Enter...',
    useCustomBtn: 'Chọn',
    activeBadge: 'Đang dùng',
    selectedBadge: 'Sẽ áp dụng',
    newBadge: 'MỚI',
    allFamilies: 'Tất cả',
    statusChipTip: img => `Model Tạo Ảnh đang dùng: ${img} — Nhấn để mở Gateway Models`,
    checkSuccessToast: (chatCount, imgCount, newCount, ms) =>
      newCount > 0
        ? `Kết nối thành công (${ms} ms): ${chatCount} model nội dung, ${imgCount} model ảnh (+${newCount} model mới!)`
        : `Kết nối ổn định (${ms} ms): ${chatCount} model nội dung, ${imgCount} model ảnh.`,
    applySuccessToast: (chatModel, imgModel) =>
      `Đã áp dụng: Nội dung [${chatModel}] • Tạo ảnh [${imgModel}]`
  }
}

async function syncLiveDesktopModel(contentModel, canonicalProvider) {
  try {
    await queryClient.invalidateQueries({ queryKey: ['model-options'] })
  } catch {
    // ignore cache invalidation errors
  }

  const sid = host.state.focusedSessionId.get() || host.state.activeSessionId.get()
  if (sid && contentModel) {
    const providerFlag = canonicalProvider || 'custom:custom-gateway'
    try {
      await host.request('config.set', {
        session_id: sid,
        key: 'model',
        value: `${contentModel} --provider ${providerFlag}`,
        confirm_expensive_model: true
      })
    } catch {
      // draft or busy session; config.yaml is already saved for next turn
    }
  }
}

function formatCheckedTime(iso) {
  if (!iso) {
    return 'Chưa kiểm tra'
  }
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) {
      return String(iso)
    }
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return String(iso)
  }
}

function ModelPickerColumn({
  title,
  subtitle,
  iconName,
  models,
  activeSavedModel,
  selectedModel,
  onSelectModel,
  searchPlaceholder,
  customPlaceholder,
  showTransport,
  t
}) {
  const [search, setSearch] = useState('')
  const [familyFilter, setFamilyFilter] = useState('ALL')
  const [customInput, setCustomInput] = useState('')

  const families = useMemo(() => {
    const set = new Set()
    for (const item of models) {
      if (item.family) {
        set.add(item.family)
      }
    }
    return ['ALL', ...Array.from(set)]
  }, [models])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return models.filter(item => {
      if (familyFilter !== 'ALL' && item.family !== familyFilter) {
        return false
      }
      if (!q) {
        return true
      }
      return (
        item.id.toLowerCase().includes(q) ||
        String(item.family || '').toLowerCase().includes(q)
      )
    })
  }, [models, search, familyFilter])

  const submitCustom = () => {
    const trimmed = customInput.trim()
    if (!trimmed) {
      return
    }
    haptic('tap')
    onSelectModel(trimmed)
    setCustomInput('')
  }

  return jsxs('div', {
    className:
      'flex min-h-[26rem] flex-col rounded-xl border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-4',
    children: [
      // Header
      jsxs('div', {
        className: 'flex items-start justify-between gap-3 pb-3',
        children: [
          jsxs('div', {
            className: 'flex items-start gap-2.5',
            children: [
              jsx('div', {
                className:
                  'mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary',
                children: jsx(Codicon, { name: iconName, size: 16 })
              }),
              jsxs('div', {
                children: [
                  jsxs('div', {
                    className: 'flex items-center gap-2',
                    children: [
                      jsx('h3', {
                        className: 'text-sm font-semibold text-foreground',
                        children: title
                      }),
                      jsx(Badge, {
                        variant: 'secondary',
                        className: 'text-[0.6875rem]',
                        children: String(models.length)
                      })
                    ]
                  }),
                  jsx('p', {
                    className: 'mt-0.5 text-xs text-(--ui-text-tertiary)',
                    children: subtitle
                  })
                ]
              })
            ]
          }),
          selectedModel
            ? jsx(Badge, {
                variant: selectedModel === activeSavedModel ? 'secondary' : 'default',
                className: 'max-w-[13rem] truncate font-mono text-[0.6875rem]',
                children: selectedModel
              })
            : null
        ]
      }),

      // Search input
      jsxs('div', {
        className: 'relative mb-2.5',
        children: [
          jsx(Input, {
            value: search,
            onChange: e => setSearch(e.target.value),
            placeholder: searchPlaceholder,
            className: 'h-8 text-xs'
          }),
          search
            ? jsx('button', {
                type: 'button',
                onClick: () => setSearch(''),
                className:
                  'absolute top-1/2 right-2 -translate-y-1/2 text-xs text-(--ui-text-tertiary) hover:text-foreground',
                children: '✕'
              })
            : null
        ]
      }),

      // Family filter chips
      families.length > 2
        ? jsx('div', {
            className: 'mb-2.5 flex flex-wrap gap-1',
            children: families.map(fam => {
              const active = familyFilter === fam
              return jsx(
                'button',
                {
                  type: 'button',
                  onClick: () => {
                    haptic('tap')
                    setFamilyFilter(fam)
                  },
                  className: cn(
                    'rounded-md px-2 py-0.5 text-[0.6875rem] transition-colors',
                    active
                      ? 'bg-primary text-primary-foreground font-medium'
                      : 'bg-(--ui-bg-tertiary) text-(--ui-text-secondary) hover:text-foreground'
                  ),
                  children: fam === 'ALL' ? t('allFamilies') : fam
                },
                fam
              )
            })
          })
        : null,

      // Scrollable model list
      jsx(ScrollArea, {
        className: 'h-72 flex-1 pr-1',
        children: jsxs('div', {
          className: 'flex flex-col gap-1',
          children: [
            filtered.length === 0
              ? jsx('div', {
                  className: 'py-8 text-center text-xs text-(--ui-text-tertiary)',
                  children: 'Không tìm thấy model phù hợp với bộ lọc.'
                })
              : null,
            ...filtered.map(item => {
              const isSelected = selectedModel === item.id
              const isSaved = activeSavedModel === item.id
              return jsx(
                RowButton,
                {
                  onClick: () => {
                    haptic('tap')
                    onSelectModel(item.id)
                  },
                  className: cn(
                    'flex w-full items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left transition-colors',
                    isSelected
                      ? 'border-primary/50 bg-primary/10 text-foreground'
                      : 'border-transparent bg-(--ui-bg-tertiary)/50 text-(--ui-text-secondary) hover:border-(--ui-stroke-secondary) hover:bg-(--chrome-action-hover) hover:text-foreground'
                  ),
                  children: [
                    jsxs('div', {
                      className: 'min-w-0 flex-1',
                      children: [
                        jsxs('div', {
                          className: 'flex items-center gap-1.5',
                          children: [
                            jsx(Codicon, {
                              name: isSelected ? 'pass-filled' : 'circle-large-outline',
                              size: 13,
                              className: isSelected ? 'text-primary shrink-0' : 'text-(--ui-text-tertiary) shrink-0'
                            }),
                            jsx('span', {
                              className: 'truncate font-mono text-xs font-medium',
                              children: item.id
                            }),
                            item.is_new
                              ? jsx(Badge, {
                                  variant: 'default',
                                  className: 'px-1.5 py-0 text-[0.625rem]',
                                  children: t('newBadge')
                                })
                              : null
                          ]
                        }),
                        jsxs('div', {
                          className: 'mt-0.5 flex items-center gap-2 pl-5 text-[0.6875rem] text-(--ui-text-tertiary)',
                          children: [
                            jsx('span', { children: item.family || 'Custom' }),
                            showTransport && item.transport
                              ? jsx('span', {
                                  children:
                                    item.transport === 'images_or_chat'
                                      ? '• Images / Chat API'
                                      : '• /v1/images/generations'
                                })
                              : null
                          ]
                        })
                      ]
                    }),
                    jsxs('div', {
                      className: 'flex shrink-0 items-center gap-1',
                      children: [
                        isSaved
                          ? jsx(Badge, {
                              variant: 'secondary',
                              className: 'text-[0.625rem]',
                              children: t('activeBadge')
                            })
                          : null,
                        isSelected && !isSaved
                          ? jsx(Badge, {
                              variant: 'outline',
                              className: 'border-primary/40 text-primary text-[0.625rem]',
                              children: t('selectedBadge')
                            })
                          : null
                      ]
                    })
                  ]
                },
                item.id
              )
            })
          ]
        })
      }),

      // Custom model manual input
      jsxs('div', {
        className: 'mt-3 flex items-center gap-2 border-t border-(--ui-stroke-secondary) pt-3',
        children: [
          jsx(Input, {
            value: customInput,
            onChange: e => setCustomInput(e.target.value),
            onKeyDown: e => {
              if (isSubmitEnter(e)) {
                e.preventDefault()
                submitCustom()
              }
            },
            placeholder: customPlaceholder,
            className: 'h-8 flex-1 font-mono text-xs'
          }),
          jsx(Button, {
            size: 'sm',
            variant: 'secondary',
            disabled: !customInput.trim(),
            onClick: submitCustom,
            children: t('useCustomBtn')
          })
        ]
      })
    ]
  })
}

function GatewayHubPage({ ctx, embedded = false }) {
  const t = usePluginI18n(ID)
  const qc = useQueryClient()
  const activeProfile = useValue(host.state.profile)

  const [autoCheck, setAutoCheck] = useState(() => ctx.storage.get('autoCheckOnOpen', true))
  const [showEndpointForm, setShowEndpointForm] = useState(false)

  const [draftContentModel, setDraftContentModel] = useState('')
  const [draftImageModel, setDraftImageModel] = useState('')
  const [draftBaseUrl, setDraftBaseUrl] = useState('')
  const [draftApiMode, setDraftApiMode] = useState('chat_completions')
  const [draftApiKey, setDraftApiKey] = useState('')
  const [syncPptMaster, setSyncPptMaster] = useState(true)
  const [lastProbeBanner, setLastProbeBanner] = useState(null)

  const initializedRef = useRef(false)

  const stateQuery = useQuery({
    queryKey: [...QUERY_KEY, activeProfile],
    queryFn: () => ctx.rest('/state', { timeoutMs: 15_000 })
  })

  const data = stateQuery.data

  useEffect(() => {
    if (!data) {
      return
    }
    if (!initializedRef.current) {
      setDraftContentModel(data.active_content_model || '')
      setDraftImageModel(data.active_image_model || '')
      setDraftBaseUrl(data.base_url || '')
      setDraftApiMode(data.api_mode || 'chat_completions')
      if (data.ppt_master && data.ppt_master.exists) {
        setSyncPptMaster(true)
      }
      initializedRef.current = true
    }
  }, [data])

  const checkMutation = useMutation({
    mutationFn: ({ silent = false } = {}) =>
      ctx
        .rest('/check', {
          method: 'POST',
          body: {
            base_url: draftBaseUrl.trim() || undefined,
            api_key: draftApiKey.trim() || undefined,
            api_mode: draftApiMode || undefined,
            persist: true
          },
          timeoutMs: 25_000
        })
        .then(res => ({ res, silent })),
    onSuccess: async ({ res, silent }) => {
      if (!res || !res.ok) {
        const msg = (res && res.error) || 'Không thể kết nối tới Custom Gateway.'
        setLastProbeBanner({ ok: false, message: msg })
        if (!silent) {
          haptic('error')
          host.notifyError(msg)
        }
        return
      }

      const newCount =
        (Array.isArray(res.new_chat_models) ? res.new_chat_models.length : 0) +
        (Array.isArray(res.new_image_models) ? res.new_image_models.length : 0)
      const summary = t(
        'checkSuccessToast',
        res.discovered_chat_count ?? (res.chat_models || []).length,
        res.discovered_image_count ?? (res.image_models || []).length,
        newCount,
        res.latency_ms ?? 0
      )
      setLastProbeBanner({
        ok: true,
        message: summary,
        latencyMs: res.latency_ms,
        newChat: res.new_chat_models || [],
        newImage: res.new_image_models || []
      })

      if (res.resolved_base_url) {
        setDraftBaseUrl(res.resolved_base_url)
      }

      qc.setQueryData([...QUERY_KEY, activeProfile], res)
      await queryClient.invalidateQueries({ queryKey: ['model-options'] }).catch(() => undefined)

      if (!silent || newCount > 0) {
        haptic('tap')
        host.notify({ kind: 'success', message: summary })
      }
    },
    onError: err => {
      const msg = err instanceof Error ? err.message : String(err)
      setLastProbeBanner({ ok: false, message: msg })
      haptic('error')
      host.notifyError(msg)
    }
  })

  // Auto-check on open when enabled (with 60s cooldown so switching tabs is instant)
  useEffect(() => {
    if (!data || !autoCheck || checkMutation.isPending) {
      return
    }
    const now = Date.now()
    if (now - lastAutoCheckAt < AUTO_CHECK_COOLDOWN_MS && (data.chat_models || []).length > 0) {
      return
    }
    lastAutoCheckAt = now
    checkMutation.mutate({ silent: true })
  }, [Boolean(data), autoCheck])

  const applyMutation = useMutation({
    mutationFn: () =>
      ctx.rest('/apply', {
        method: 'POST',
        body: {
          content_model: draftContentModel.trim() || undefined,
          image_model: draftImageModel.trim() || undefined,
          base_url: draftBaseUrl.trim() || undefined,
          api_mode: draftApiMode || undefined,
          api_key: draftApiKey.trim() || undefined,
          sync_ppt_master: syncPptMaster
        },
        timeoutMs: 25_000
      }),
    onSuccess: async res => {
      setDraftApiKey('')
      qc.setQueryData([...QUERY_KEY, activeProfile], res)
      await syncLiveDesktopModel(res.active_content_model, res.canonical_provider)
      haptic('tap')
      host.notify({
        kind: 'success',
        message: t('applySuccessToast', res.active_content_model, res.active_image_model)
      })
    },
    onError: err => {
      const msg = err instanceof Error ? err.message : String(err)
      haptic('error')
      host.notifyError(msg)
    }
  })

  const chatModels = useMemo(() => {
    const base = Array.isArray(data?.chat_models) ? [...data.chat_models] : []
    if (draftContentModel && !base.some(m => m.id === draftContentModel)) {
      base.unshift({ id: draftContentModel, family: 'Custom / Selected', is_new: false })
    }
    return base
  }, [data?.chat_models, draftContentModel])

  const imageModels = useMemo(() => {
    const base = Array.isArray(data?.image_models) ? [...data.image_models] : []
    if (draftImageModel && !base.some(m => m.id === draftImageModel)) {
      base.unshift({
        id: draftImageModel,
        family: 'Custom / Selected',
        transport: 'images_api',
        is_new: false
      })
    }
    return base
  }, [data?.image_models, draftImageModel])

  const hasUnsavedChanges = Boolean(
    data &&
      ((draftContentModel && draftContentModel !== data.active_content_model) ||
        (draftImageModel && draftImageModel !== data.active_image_model) ||
        (draftBaseUrl && draftBaseUrl.trim() !== (data.base_url || '').trim()) ||
        (draftApiMode && draftApiMode !== data.api_mode) ||
        Boolean(draftApiKey.trim()) ||
        (syncPptMaster && data.ppt_master?.exists && !data.ppt_master?.synced))
  )

  const toggleAutoCheck = checked => {
    setAutoCheck(checked)
    ctx.storage.set('autoCheckOnOpen', checked)
  }

  if (stateQuery.isLoading) {
    return jsxs('div', {
      className: 'flex h-full items-center justify-center gap-2 p-8 text-sm text-(--ui-text-secondary)',
      children: [
        jsx(Codicon, { name: 'loading', spinning: true, size: 16 }),
        jsx('span', { children: 'Đang tải cấu hình Custom Gateway Hub...' })
      ]
    })
  }

  if (stateQuery.isError) {
    const errMsg =
      stateQuery.error instanceof Error ? stateQuery.error.message : String(stateQuery.error)
    return jsxs('div', {
      className: 'flex h-full flex-col items-center justify-center gap-3 p-8 text-center',
      children: [
        jsx('div', {
          className: 'text-sm font-medium text-destructive',
          children: 'Không thể kết nối tới plugin backend (/api/plugins/custom-gateway-hub/state)'
        }),
        jsx('div', {
          className: 'max-w-lg text-xs text-(--ui-text-tertiary)',
          children: errMsg
        }),
        jsx(Button, {
          size: 'sm',
          onClick: () => stateQuery.refetch(),
          children: 'Thử lại'
        })
      ]
    })
  }

  const connectionTone =
    lastProbeBanner?.ok === false
      ? 'bad'
      : data?.has_api_key && data?.base_url
        ? 'good'
        : 'warn'

  return jsx(ScrollArea, {
    className: 'h-full w-full',
    children: jsxs('div', {
      className: cn(
        'mx-auto flex w-full max-w-6xl flex-col gap-4',
        embedded ? 'p-2' : 'p-6'
      ),
      children: [
        // Top Hero & Connection Card
        jsxs('div', {
          className:
            'flex flex-col gap-3 rounded-xl border border-(--ui-stroke-secondary) bg-(--ui-bg-secondary) p-4',
          children: [
            jsxs('div', {
              className: 'flex flex-wrap items-start justify-between gap-3',
              children: [
                jsxs('div', {
                  className: 'min-w-0 flex-1',
                  children: [
                    jsxs('div', {
                      className: 'flex flex-wrap items-center gap-2',
                      children: [
                        jsx(StatusDot, { tone: connectionTone }),
                        jsx('h2', {
                          className: 'text-base font-semibold text-foreground',
                          children: t('pageTitle')
                        }),
                        jsx(Badge, {
                          variant: 'secondary',
                          className: 'font-mono text-[0.6875rem]',
                          children: data?.provider_slug || 'custom-gateway'
                        }),
                        (lastProbeBanner?.latencyMs || data?.last_latency_ms)
                          ? jsx(Badge, {
                              variant: 'outline',
                              className: 'font-mono text-[0.6875rem]',
                              children: `${lastProbeBanner?.latencyMs || data?.last_latency_ms} ms`
                            })
                          : null
                      ]
                    }),
                    jsx('p', {
                      className: 'mt-1 text-xs text-(--ui-text-secondary)',
                      children: t('pageSubtitle')
                    }),
                    jsxs('div', {
                      className:
                        'mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[0.6875rem] text-(--ui-text-tertiary)',
                      children: [
                        jsxs('span', {
                          className: 'font-mono',
                          children: ['Endpoint: ', data?.base_url || '(chưa đặt)']
                        }),
                        jsxs('span', {
                          children: [
                            'API Key: ',
                            data?.has_api_key
                              ? `${data.masked_api_key} (${data.key_env})`
                              : 'Chưa cấu hình'
                          ]
                        }),
                        jsxs('span', {
                          children: ['Cập nhật lúc: ', formatCheckedTime(data?.last_checked_at)]
                        })
                      ]
                    })
                  ]
                }),

                // Action buttons
                jsxs('div', {
                  className: 'flex flex-wrap items-center gap-2',
                  children: [
                    jsx(Button, {
                      variant: 'outline',
                      size: 'sm',
                      onClick: () => setShowEndpointForm(v => !v),
                      children: jsxs('span', {
                        className: 'inline-flex items-center gap-1.5',
                        children: [
                          jsx(Codicon, { name: 'settings-gear', size: 14 }),
                          jsx('span', { children: t('endpointConfig') })
                        ]
                      })
                    }),
                    jsx(Button, {
                      variant: 'default',
                      size: 'sm',
                      disabled: checkMutation.isPending,
                      onClick: () => {
                        haptic('tap')
                        checkMutation.mutate({ silent: false })
                      },
                      children: jsxs('span', {
                        className: 'inline-flex items-center gap-1.5',
                        children: [
                          jsx(Codicon, {
                            name: 'sync',
                            size: 14,
                            spinning: checkMutation.isPending
                          }),
                          jsx('span', {
                            children: checkMutation.isPending ? t('checkingBtn') : t('checkBtn')
                          })
                        ]
                      })
                    })
                  ]
                })
              ]
            }),

            // Probe status banner
            lastProbeBanner
              ? jsxs('div', {
                  className: cn(
                    'flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs',
                    lastProbeBanner.ok
                      ? 'border-primary/30 bg-primary/10 text-foreground'
                      : 'border-destructive/40 bg-destructive/10 text-destructive'
                  ),
                  children: [
                    jsxs('div', {
                      className: 'flex items-center gap-2',
                      children: [
                        jsx(Codicon, {
                          name: lastProbeBanner.ok ? 'check' : 'warning',
                          size: 14
                        }),
                        jsx('span', { children: lastProbeBanner.message })
                      ]
                    }),
                    jsx('button', {
                      type: 'button',
                      onClick: () => setLastProbeBanner(null),
                      className: 'text-(--ui-text-tertiary) hover:text-foreground',
                      children: '✕'
                    })
                  ]
                })
              : null,

            // Collapsible Endpoint & API Key editor
            showEndpointForm
              ? jsxs('div', {
                  className:
                    'mt-1 grid grid-cols-1 gap-3 rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-tertiary)/50 p-3 md:grid-cols-3',
                  children: [
                    jsxs('div', {
                      className: 'flex flex-col gap-1',
                      children: [
                        jsx('label', {
                          className: 'text-[0.6875rem] font-medium text-(--ui-text-secondary)',
                          children: 'Base URL (/v1)'
                        }),
                        jsx(Input, {
                          value: draftBaseUrl,
                          onChange: e => setDraftBaseUrl(e.target.value),
                          placeholder: 'https://your-gateway.example.com/v1',
                          className: 'h-8 font-mono text-xs'
                        })
                      ]
                    }),
                    jsxs('div', {
                      className: 'flex flex-col gap-1',
                      children: [
                        jsx('label', {
                          className: 'text-[0.6875rem] font-medium text-(--ui-text-secondary)',
                          children: 'API Wire Mode'
                        }),
                        jsxs('div', {
                          className: 'flex gap-1',
                          children: ['chat_completions', 'codex_responses', 'anthropic_messages'].map(
                            mode =>
                              jsx(
                                'button',
                                {
                                  type: 'button',
                                  onClick: () => setDraftApiMode(mode),
                                  className: cn(
                                    'flex-1 truncate rounded-md border px-2 py-1 font-mono text-[0.6875rem] transition-colors',
                                    draftApiMode === mode
                                      ? 'border-primary bg-primary/15 text-foreground font-medium'
                                      : 'border-(--ui-stroke-secondary) text-(--ui-text-tertiary) hover:text-foreground'
                                  ),
                                  children: mode.replace('_', ' ')
                                },
                                mode
                              )
                          )
                        })
                      ]
                    }),
                    jsxs('div', {
                      className: 'flex flex-col gap-1',
                      children: [
                        jsx('label', {
                          className: 'text-[0.6875rem] font-medium text-(--ui-text-secondary)',
                          children: `API Key (${data?.masked_api_key || 'chưa lưu'})`
                        }),
                        jsx(Input, {
                          type: 'password',
                          value: draftApiKey,
                          onChange: e => setDraftApiKey(e.target.value),
                          placeholder: 'Để trống nếu giữ nguyên API key hiện tại...',
                          className: 'h-8 font-mono text-xs'
                        })
                      ]
                    })
                  ]
                })
              : null,

            // Preferences bar inside header card
            jsxs('div', {
              className:
                'flex flex-wrap items-center justify-between gap-3 border-t border-(--ui-stroke-secondary) pt-3',
              children: [
                jsxs('div', {
                  className: 'flex flex-wrap items-center gap-5',
                  children: [
                    jsxs('label', {
                      className: 'flex cursor-pointer items-center gap-2 text-xs text-(--ui-text-secondary)',
                      children: [
                        jsx(Switch, {
                          size: 'xs',
                          checked: autoCheck,
                          onCheckedChange: toggleAutoCheck
                        }),
                        jsx('span', { children: t('autoCheckLabel') })
                      ]
                    }),
                    data?.ppt_master?.exists
                      ? jsxs('label', {
                          className:
                            'flex cursor-pointer items-center gap-2 text-xs text-(--ui-text-secondary)',
                          children: [
                            jsx(Switch, {
                              size: 'xs',
                              checked: syncPptMaster,
                              onCheckedChange: setSyncPptMaster
                            }),
                            jsx('span', { children: t('pptSyncLabel') }),
                            jsx(Badge, {
                              variant: data.ppt_master.synced ? 'secondary' : 'outline',
                              className: 'text-[0.625rem]',
                              children: data.ppt_master.synced
                                ? `PPT: ${data.ppt_master.current_model}`
                                : 'PPT chưa đồng bộ'
                            })
                          ]
                        })
                      : null
                  ]
                }),

                // Save & Apply button
                jsxs('div', {
                  className: 'flex items-center gap-2',
                  children: [
                    !hasUnsavedChanges
                      ? jsxs('span', {
                          className: 'inline-flex items-center gap-1 text-xs text-(--ui-text-tertiary)',
                          children: [
                            jsx(Codicon, { name: 'check-all', size: 14 }),
                            jsx('span', { children: t('savedLabel') })
                          ]
                        })
                      : jsx('span', {
                          className: 'text-xs font-medium text-primary',
                          children: 'Có thay đổi chưa lưu'
                        }),
                    jsx(Button, {
                      variant: hasUnsavedChanges ? 'default' : 'secondary',
                      size: 'sm',
                      disabled: applyMutation.isPending || (!draftContentModel && !draftImageModel),
                      onClick: () => applyMutation.mutate(),
                      children: jsxs('span', {
                        className: 'inline-flex items-center gap-1.5',
                        children: [
                          jsx(Codicon, {
                            name: applyMutation.isPending ? 'loading' : 'save',
                            spinning: applyMutation.isPending,
                            size: 14
                          }),
                          jsx('span', {
                            children: applyMutation.isPending ? t('savingBtn') : t('saveBtn')
                          })
                        ]
                      })
                    })
                  ]
                })
              ]
            })
          ]
        }),

        // Two-Column Model Pickers: Content Model vs Image Model
        jsxs('div', {
          className: 'grid grid-cols-1 gap-4 lg:grid-cols-2',
          children: [
            jsx(ModelPickerColumn, {
              title: t('contentCardTitle'),
              subtitle: t('contentCardSub'),
              iconName: 'comment-discussion',
              models: chatModels,
              activeSavedModel: data?.active_content_model || '',
              selectedModel: draftContentModel,
              onSelectModel: setDraftContentModel,
              searchPlaceholder: t('searchChatPlaceholder'),
              customPlaceholder: t('customModelPlaceholder'),
              showTransport: false,
              t
            }),
            jsx(ModelPickerColumn, {
              title: t('imageCardTitle'),
              subtitle: t('imageCardSub'),
              iconName: 'device-camera',
              models: imageModels,
              activeSavedModel: data?.active_image_model || '',
              selectedModel: draftImageModel,
              onSelectModel: setDraftImageModel,
              searchPlaceholder: t('searchImagePlaceholder'),
              customPlaceholder: t('customModelPlaceholder'),
              showTransport: true,
              t
            })
          ]
        })
      ]
    })
  })
}

function GatewayStatusChip({ ctx }) {
  const t = usePluginI18n(ID)
  const activeProfile = useValue(host.state.profile)

  const stateQuery = useQuery({
    queryKey: [...QUERY_KEY, activeProfile],
    queryFn: () => ctx.rest('/state', { timeoutMs: 15_000 }),
    staleTime: 30_000
  })

  const imgModel = stateQuery.data?.active_image_model || 'gpt-image'

  return jsx(Tip, {
    label: t('statusChipTip', imgModel),
    children: jsxs('button', {
      type: 'button',
      onClick: () => {
        haptic('tap')
        host.navigate(ROUTE_PATH)
      },
      className: cn(
        'inline-flex h-full items-center gap-1.5 px-2 text-[0.6875rem] transition-colors',
        'text-(--ui-text-tertiary) hover:bg-(--chrome-action-hover) hover:text-foreground'
      ),
      children: [
        jsx(Codicon, { name: 'device-camera', size: 12 }),
        jsx('span', { className: 'max-w-[9.5rem] truncate font-mono', children: imgModel })
      ]
    })
  })
}

export default {
  id: ID,
  name: 'Custom Gateway Hub',
  description:
    'Check Connection (/v1/models), tự động phát hiện model mới và chọn riêng Model Sinh Nội Dung & Model Tạo Ảnh.',
  register(ctx) {
    ctx.i18n.register(MESSAGES)

    // Listen to live backend events so open tabs update automatically
    ctx.onEvent('*', event => {
      if (event && event.plugin === ID) {
        queryClient.invalidateQueries({ queryKey: QUERY_KEY }).catch(() => undefined)
      }
    })

    // 1. Full Workspace Route (/gateway-hub)
    ctx.register({
      id: 'route',
      area: ROUTES_AREA,
      title: 'Gateway Models',
      data: { path: ROUTE_PATH },
      render: () => jsx(GatewayHubPage, { ctx, embedded: false })
    })

    // 2. Left Sidebar Navigation Row ("Gateway Models")
    ctx.register({
      id: 'sidebar-nav',
      area: SIDEBAR_NAV_AREA,
      order: 25,
      data: {
        codicon: 'server-process',
        label: 'Gateway Models',
        path: ROUTE_PATH
      }
    })

    // 3. Bottom-Right Statusbar Quick Chip (shows active Image Model beside Chat Model)
    ctx.register({
      id: 'statusbar-image-model',
      area: STATUSBAR_AREAS.right,
      order: 125,
      render: () => jsx(GatewayStatusChip, { ctx })
    })

    // 4. Command Palette Shortcuts (Ctrl+K / Cmd+K)
    ctx.register({
      id: 'palette-open-hub',
      area: PALETTE_AREA,
      data: {
        id: 'open-custom-gateway-hub',
        label: 'Gateway Models: Mở bảng chọn Model Sinh Nội Dung & Tạo Ảnh',
        keywords: ['gateway', 'custom', 'model', 'image', 'chat', 'chon model', 'anh'],
        run: () => host.navigate(ROUTE_PATH)
      }
    })

    ctx.register({
      id: 'palette-check-connection',
      area: PALETTE_AREA,
      data: {
        id: 'check-custom-gateway-connection',
        label: 'Gateway Models: Check Connection & Tải danh sách Model mới',
        keywords: ['check', 'connection', 'sync', 'refresh', 'models', 'ket noi', 'tai model'],
        run: async () => {
          try {
            const res = await ctx.rest('/check', {
              method: 'POST',
              body: { persist: true },
              timeoutMs: 25_000
            })
            if (res && res.ok) {
              await queryClient.invalidateQueries({ queryKey: QUERY_KEY }).catch(() => undefined)
              await queryClient
                .invalidateQueries({ queryKey: ['model-options'] })
                .catch(() => undefined)
              host.notify({
                kind: 'success',
                message: `Check Connection OK (${res.latency_ms} ms): ${res.discovered_chat_count} model nội dung, ${res.discovered_image_count} model ảnh.`
              })
            } else {
              host.notifyError((res && res.error) || 'Check Connection thất bại.')
            }
          } catch (err) {
            host.notifyError(err instanceof Error ? err.message : String(err))
          }
        }
      }
    })

    // 5. Settings -> Plugins -> Custom Gateway Hub
    ctx.registerSettingsPage?.({
      id: 'hub-settings',
      title: 'Custom Gateway Hub',
      icon: 'server-process',
      order: 10,
      render: () => jsx(GatewayHubPage, { ctx, embedded: true })
    })
  }
}
