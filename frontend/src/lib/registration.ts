import { translate, translateChoiceLabel, type Language } from '@/lib/i18n'

type ChoiceOption = {
  value: string
  label: string
}

function getOptionLabel(value: string, options: ChoiceOption[] = [], language?: Language) {
  return translateChoiceLabel(value, options.find(item => item.value === value)?.label || value, language)
}

export function buildRegistrationOptions(platformMeta: any, language?: Language) {
  const supportedModes: string[] = platformMeta?.supported_identity_modes || []
  const identityModeOptions: ChoiceOption[] = platformMeta?.supported_identity_mode_options || []
  const options: Array<{
    key: string
    label: string
    description: string
    identityProvider: string
  }> = []

  if (supportedModes.includes('mailbox')) {
    const label = getOptionLabel('mailbox', identityModeOptions, language)
    options.push({
      key: 'mailbox',
      label,
      description: translate('registration.mailboxDescription', language, { label }),
      identityProvider: 'mailbox',
    })
  }

  return options
}

export function buildExecutorOptions(
  supportedExecutors: string[],
  executorOptions: ChoiceOption[] = [],
  language?: Language,
) {
  return supportedExecutors.map((executor) => {
    const option = {
      value: executor,
      label: getOptionLabel(executor, executorOptions, language),
      description: '',
      disabled: false,
      reason: '',
    }

    if (executor === 'protocol') {
      option.description = translate('executor.protocolDescription', language)
      return option
    }

    if (executor === 'headless') {
      option.description = translate('executor.headlessMailboxDescription', language)
      return option
    }

    option.description = translate('executor.headedDescription', language)
    return option
  })
}
