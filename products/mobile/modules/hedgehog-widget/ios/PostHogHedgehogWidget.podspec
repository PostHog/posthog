require 'json'

package = JSON.parse(File.read(File.join(__dir__, '..', 'package.json')))

# Not named HedgehogWidget: the widget extension target already owns that Swift module name, and the
# appex's module would shadow this one when ExpoModulesProvider imports it.
Pod::Spec.new do |s|
  s.name           = 'PostHogHedgehogWidget'
  s.version        = package['version']
  s.summary        = 'Hands the hedgehog choreography to the iOS home-screen widget'
  s.license        = 'MIT'
  s.author         = 'PostHog'
  s.homepage       = 'https://posthog.com'
  s.platforms      = { :ios => '16.4' }
  s.swift_version  = '5.9'
  s.source         = { git: 'https://github.com/PostHog/posthog.git' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'
  s.frameworks = 'WidgetKit'

  s.source_files = '**/*.{h,m,swift}'
  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }
end
