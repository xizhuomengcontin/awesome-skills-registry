package registry

import "time"

#Skill: {
	// Globally unique identifier: {owner}-{repo}-{skill_dir}
	id: =~"^[a-zA-Z0-9][a-zA-Z0-9._-]*$"

	// Human-readable skill name
	display_name: string & !=""

	// What the skill does and when to trigger it
	description: string & !=""

	// GitHub org or user who published the skill (defaults to repo owner)
	authors: [string, ...string]

	// True when the publisher is the authoritative vendor for the skill's domain
	is_official: bool

	// Pointer back to the source repository
	source: #Source

	// Freeform discovery labels; lowercase, dash-separated
	tags: [...#Tag]

	// Primary grouping bucket
	category: #Category

	// Extensible bag for future structured data (install hints, pricing, etc.)
	metadata: {...}

	// ISO-8601 date the entry was first added
	added_at: time.Format("2006-01-02")
}

#Source: {
	// Path within the repo to the skill directory (e.g. /skills/frontend-design)
	path: =~"^/"

	// GitHub owner/repo
	repo: =~"^[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+$"
}

#Tag: string & =~"^[a-z0-9]+(-[a-z0-9]+)*$"

#Category:
	*"none" |
	"coding" |
	"design" |
	"productivity" |
	"marketing" |
	"business" |
	"data-ai" |
	"science" |
	"creative" |
	"health" |
	"legal" |
	"miscellaneous"
